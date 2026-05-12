import logging
import traceback
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

try:
    from psycopg2 import errors as pg_errors
except ImportError:
    pg_errors = None

_logger = logging.getLogger(__name__)

QB_ENTITY_TYPES = [
    ('customer', 'Customer'),
    ('vendor', 'Vendor'),
    ('product', 'Product'),
    ('account', 'Account'),
    ('invoice', 'Invoice'),
    ('bill', 'Bill'),
    ('payment', 'Payment'),
    ('bill_payment', 'Bill Payment'),
    ('journal_entry', 'Journal Entry'),
    ('credit_memo', 'Credit Memo'),
    ('estimate', 'Estimate'),
    ('tax_code', 'Tax Code'),
    ('sales_receipt', 'Sales Receipt'),
    ('refund_receipt', 'Refund Receipt'),
    ('purchase_order', 'Purchase Order'),
    ('expense', 'Expense / Purchase'),
    ('deposit', 'Deposit'),
    ('transfer', 'Transfer'),
    ('employee', 'Employee'),
    ('department', 'Department'),
    ('time_activity', 'Time Activity'),
    ('project', 'Project'),
    ('class', 'Class'),
    ('term', 'Payment Term'),
    ('attachment', 'Attachment'),
    ('vendor_credit', 'Vendor Credit'),
    ('exchange_rate', 'Exchange Rate'),
    ('company_info', 'Company Info'),
    ('payroll_compensation', 'Payroll Compensation'),
    ('payroll_employee', 'Payroll Employee'),
    ('payroll_pay_item', 'Payroll Pay Item'),
    ('payroll_schedule', 'Payroll Pay Schedule'),
    ('payroll_check', 'Payroll Check'),
    ('work_location', 'Work Location'),
    ('inventory_adjustment', 'Inventory Adjustment'),
    ('timesheet', 'Timesheet (QBT)'),
    ('report', 'Financial Report'),
    ('recurring_transaction', 'Recurring Transaction'),
    ('custom_field_definition', 'Custom Field Definition'),
    ('employee_benefit', 'Employee Benefit'),
    ('payroll_settings', 'Payroll Settings'),
]

MAX_RETRIES = 5
BACKOFF_SECONDS = [30, 60, 120, 240, 480]


class QuickbooksSyncQueue(models.Model):
    _name = 'quickbooks.sync.queue'
    _description = 'QuickBooks Sync Queue'
    _order = 'priority desc, create_date asc'
    _rec_name = 'display_name_computed'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    entity_type = fields.Selection(QB_ENTITY_TYPES, required=True, index=True)
    direction = fields.Selection(
        [('push', 'Odoo → QBO'), ('pull', 'QBO → Odoo')],
        required=True,
    )
    operation = fields.Selection(
        [('create', 'Create'), ('update', 'Update'), ('delete', 'Delete')],
        required=True,
    )
    odoo_record_id = fields.Integer(string='Odoo Record ID')
    odoo_model = fields.Char(string='Odoo Model')
    qb_entity_id = fields.Char(string='QB Entity ID')
    state = fields.Selection(
        [('pending', 'Pending'),
         ('processing', 'Processing'),
         ('done', 'Done'),
         ('failed', 'Failed'),
         ('conflict', 'Conflict')],
        default='pending', required=True, index=True,
    )
    priority = fields.Integer(default=10)
    retry_count = fields.Integer(default=0)
    next_retry_at = fields.Datetime(string='Next Retry At')
    error_message = fields.Text(string='Last Error')
    idempotency_key = fields.Char(
        string='Idempotency Key', index=True,
        help='Prevents duplicate processing of the same event.',
    )
    display_name_computed = fields.Char(
        compute='_compute_display_name_computed', store=True,
    )

    @api.depends('entity_type', 'direction', 'operation', 'state')
    def _compute_display_name_computed(self):
        for rec in self:
            rec.display_name_computed = '%s %s %s [%s]' % (
                rec.direction or '', rec.operation or '',
                rec.entity_type or '', rec.state or '',
            )

    _idempotency_uniq = models.Constraint(
        'unique(idempotency_key)',
        'Duplicate sync job detected (same idempotency key).',
    )

    @api.model
    def enqueue(self, entity_type, direction, operation,
                odoo_record_id=None, odoo_model=None,
                qb_entity_id=None, company=None,
                priority=10, idempotency_key=None):
        company = company or self.env.company
        if idempotency_key:
            existing = self.sudo().search([
                ('idempotency_key', '=', idempotency_key),
            ], limit=1)
            if existing:
                _logger.debug('Duplicate queue job skipped: %s', idempotency_key)
                return existing
        vals = {
            'company_id': company.id,
            'entity_type': entity_type,
            'direction': direction,
            'operation': operation,
            'odoo_record_id': odoo_record_id,
            'odoo_model': odoo_model,
            'qb_entity_id': qb_entity_id,
            'priority': priority,
            'idempotency_key': idempotency_key,
        }
        try:
            return self.sudo().create(vals)
        except Exception as e:
            if (
                pg_errors is not None
                and isinstance(e, pg_errors.UniqueViolation)
                and idempotency_key
            ):
                self.env.cr.rollback()
                _logger.debug('Duplicate queue job skipped: %s', idempotency_key)
                return self.sudo().search([
                    ('idempotency_key', '=', idempotency_key),
                ], limit=1)
            raise

    def action_retry(self):
        for rec in self.filtered(lambda r: r.state in ('failed', 'conflict')):
            rec.write({
                'state': 'pending',
                'retry_count': 0,
                'next_retry_at': False,
                'error_message': False,
            })

    def action_cancel(self):
        for rec in self:
            rec.state = 'done'

    def _mark_failed(self, error_msg):
        self.ensure_one()
        retry = self.retry_count + 1
        if retry >= MAX_RETRIES:
            self.write({
                'state': 'failed',
                'retry_count': retry,
                'error_message': error_msg,
            })
            self._raise_failure_activity(error_msg)
        else:
            backoff = BACKOFF_SECONDS[min(retry - 1, len(BACKOFF_SECONDS) - 1)]
            self.write({
                'state': 'pending',
                'retry_count': retry,
                'next_retry_at': fields.Datetime.now() + timedelta(seconds=backoff),
                'error_message': error_msg,
            })

    def _raise_failure_activity(self, error_msg):
        """Surface a permanent sync failure on the underlying Odoo record.

        Uses the native ``mail.activity`` system (a To-do / warning) on the
        record that failed to sync, assigned to the QuickBooks Manager
        group. This replaces the previous outbound email and removes the
        need for a dedicated Sync Queue UI to triage failures.
        """
        self.ensure_one()
        if not self.odoo_model or not self.odoo_record_id:
            return
        if self.odoo_model not in self.env:
            return
        record = self.env[self.odoo_model].sudo().browse(self.odoo_record_id)
        if not record.exists():
            return
        if not hasattr(record, 'activity_schedule'):
            return
        manager_group = self.env.ref(
            'quickbooks_api_connector.group_qb_manager',
            raise_if_not_found=False,
        )
        responsible = (
            manager_group.users[:1] if manager_group and manager_group.users
            else self.env.user
        )
        try:
            record.activity_schedule(
                'mail.mail_activity_data_warning',
                summary='QuickBooks sync failed: %s %s' % (
                    self.direction or '', self.entity_type or '',
                ),
                note=(error_msg or '')[:4000],
                user_id=responsible.id,
            )
        except Exception:
            _logger.exception(
                'Failed to schedule QB failure activity on %s(%s)',
                self.odoo_model, self.odoo_record_id,
            )

    def process_pending_jobs(self, batch_size=50):
        now = fields.Datetime.now()
        jobs = self.search([
            ('state', '=', 'pending'),
            '|',
            ('next_retry_at', '=', False),
            ('next_retry_at', '<=', now),
        ], limit=batch_size)

        engine = self.env['qb.sync.engine']
        for job in jobs:
            job.state = 'processing'
            self.env.cr.commit()
            try:
                engine.execute_job(job)
                job.state = 'done'
            except Exception as e:
                _logger.exception('Sync job %s failed', job.id)
                self.env.cr.rollback()
                job._mark_failed(
                    '%s\n%s' % (str(e), traceback.format_exc())
                )
            finally:
                self.env.cr.commit()

    def process_sync_queue(self):
        configs = self.env['quickbooks.config'].search([
            ('state', '=', 'connected'),
        ])
        engine = self.env['qb.sync.engine']
        for config in configs:
            try:
                engine.run_full_sync(config)
            except Exception:
                _logger.exception(
                    'Full sync failed for company %s', config.company_id.name,
                )

    @api.autovacuum
    def _gc_old_done_jobs(self):
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=30)
        self.search([
            ('state', '=', 'done'),
            ('create_date', '<', limit_date),
        ]).unlink()
