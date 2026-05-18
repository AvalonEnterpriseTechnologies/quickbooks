import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QuickbooksMigrationWizard(models.TransientModel):
    _name = 'quickbooks.migration.wizard'
    _description = 'QuickBooks Initial Data Migration'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    direction = fields.Selection(
        [('import', 'Import from QuickBooks → Odoo'),
         ('export', 'Export from Odoo → QuickBooks'),
         ('both', 'Full Bidirectional Sync')],
        default='import', required=True,
    )
    mode = fields.Selection(
        [('dry_run', 'Dry Run'), ('live', 'Live Migration')],
        default='live',
        required=True,
    )
    migrate_accounts = fields.Boolean(default=True, string='Chart of Accounts')
    migrate_tax_codes = fields.Boolean(default=True, string='Tax Codes')
    migrate_customers = fields.Boolean(default=True, string='Customers')
    migrate_vendors = fields.Boolean(default=True, string='Vendors')
    migrate_projects = fields.Boolean(default=True, string='Projects')
    migrate_products = fields.Boolean(default=True, string='Products / Items')
    migrate_estimates = fields.Boolean(
        default=True,
        string='Estimates / Quotations',
        help='Pull QBO Estimates as Odoo Sales Orders (sale.order). '
             'Required so Invoice -> Estimate links can be rebuilt.',
    )
    migrate_invoices = fields.Boolean(default=True, string='Invoices')
    migrate_credit_memos = fields.Boolean(
        default=True,
        string='Credit Memos',
        help='Pull QBO CreditMemos as Odoo refund invoices, with their '
             'LinkedTxn -> Invoice reversal preserved.',
    )
    migrate_sales_receipts = fields.Boolean(
        default=False,
        string='Sales Receipts',
        help='Pull QBO SalesReceipts as posted Odoo invoices + auto-reconciled '
             'payments against the deposit account.',
    )
    migrate_refund_receipts = fields.Boolean(
        default=False,
        string='Refund Receipts',
        help='Pull QBO RefundReceipts as Odoo refund invoices, with their '
             'LinkedTxn -> CreditMemo link preserved.',
    )
    migrate_bills = fields.Boolean(default=True, string='Bills')
    migrate_payments = fields.Boolean(default=True, string='Payments')
    migrate_journal_entries = fields.Boolean(default=False, string='Journal Entries')
    migrate_inventory_adjustments = fields.Boolean(
        default=False, string='Inventory Adjustments',
    )
    # Legacy "all-payroll-in-one" toggle. Kept on the model so older code
    # paths (server actions, scripted runs) continue to work, but the UI
    # now exposes the individual phases below.
    migrate_payroll = fields.Boolean(default=False, string='Payroll Read Data (Legacy)')
    migrate_payroll_settings_data = fields.Boolean(
        default=False, string='Payroll Settings Snapshot',
    )
    migrate_pay_schedules = fields.Boolean(default=True, string='Pay Schedules')
    migrate_pay_items = fields.Boolean(default=True, string='Pay Items')
    migrate_work_locations = fields.Boolean(default=True, string='Work Locations')
    migrate_payroll_employees = fields.Boolean(default=True, string='Payroll Employees')
    migrate_payroll_tax_setup = fields.Boolean(
        default=True, string='Payroll Tax Setup (W-4 / state)',
    )
    migrate_payroll_compensations = fields.Boolean(
        default=True, string='Payroll Compensations',
    )
    migrate_payroll_checks = fields.Boolean(
        default=True, string='Payroll Checks (history)',
    )
    migrate_opening_balances = fields.Boolean(
        default=True,
        string='Opening Balances / Trial Balance Snapshot',
        help='Queue financial reports after the Chart of Accounts so QBO opening '
             'and current balances can be validated before posting any Odoo '
             'opening-balance journal entries.',
    )
    migrate_recurring_transactions = fields.Boolean(
        default=False,
        string='Recurring Transactions',
    )
    migrate_custom_fields = fields.Boolean(default=False, string='Custom Fields')
    migrate_employee_benefits = fields.Boolean(default=False, string='Employee Benefits')
    migrate_payroll_settings = fields.Boolean(default=False, string='Payroll Settings')
    migrate_attachments = fields.Boolean(default=False, string='Attachments')

    def action_start_migration(self):
        """Queue migration jobs in dependency order."""
        self.ensure_one()
        config = self.env['quickbooks.config'].get_config(self.company_id)
        if config.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')

        engine = self.env['qb.sync.engine']
        ordered_entities = []

        if self.migrate_accounts:
            ordered_entities.append('account')
        if self.migrate_opening_balances:
            ordered_entities.append('report')
        if self.migrate_tax_codes:
            ordered_entities.append('tax_code')
        if self.migrate_customers:
            ordered_entities.append('customer')
        if self.migrate_vendors:
            ordered_entities.append('vendor')
        if self.migrate_projects:
            ordered_entities.append('project')
        if self.migrate_products:
            ordered_entities.append('product')
        if self.migrate_recurring_transactions:
            ordered_entities.append('recurring_transaction')
        if self.migrate_custom_fields:
            ordered_entities.append('custom_field_definition')
        # Sales-document chain (parents before children so LinkedTxn
        # references resolve in a single pass; relinker still runs at
        # the end to mop up out-of-order arrivals from CDC / retries).
        if self.migrate_estimates:
            ordered_entities.append('estimate')
        if self.migrate_invoices:
            ordered_entities.append('invoice')
        if self.migrate_credit_memos:
            ordered_entities.append('credit_memo')
        if self.migrate_sales_receipts:
            ordered_entities.append('sales_receipt')
        if self.migrate_refund_receipts:
            ordered_entities.append('refund_receipt')
        if self.migrate_bills:
            ordered_entities.append('bill')
        if self.migrate_payments:
            ordered_entities.append('payment')
            ordered_entities.append('bill_payment')
        if self.migrate_journal_entries:
            ordered_entities.append('journal_entry')
        if self.migrate_inventory_adjustments:
            ordered_entities.append('inventory_adjustment')
        # Payroll runs in dependency order: settings + work locations +
        # schedules + items seed the structure, employees + tax setup
        # populate the per-employee surface, and only then do compensations
        # / checks / benefits hang off the now-complete graph.
        if self.migrate_payroll_settings_data or self.migrate_payroll:
            ordered_entities.append('payroll_settings')
        if self.migrate_work_locations or self.migrate_payroll:
            ordered_entities.append('work_location')
        if self.migrate_pay_schedules or self.migrate_payroll:
            ordered_entities.append('payroll_schedule')
        if self.migrate_pay_items or self.migrate_payroll:
            ordered_entities.append('payroll_pay_item')
        if self.migrate_payroll_employees or self.migrate_payroll:
            ordered_entities.append('payroll_employee')
        if self.migrate_payroll_tax_setup or self.migrate_payroll:
            ordered_entities.append('payroll_tax_setup')
        if self.migrate_payroll_compensations or self.migrate_payroll:
            ordered_entities.append('payroll_compensation')
        if self.migrate_payroll_checks or self.migrate_payroll:
            ordered_entities.append('payroll_check')
        if self.migrate_employee_benefits:
            ordered_entities.append('employee_benefit')
        if self.migrate_payroll_settings:
            ordered_entities.append('payroll_settings')
        if self.migrate_attachments:
            ordered_entities.append('attachment')

        directions = []
        if self.direction in ('import', 'both'):
            directions.append('pull')
        if self.direction in ('export', 'both'):
            directions.append('push')

        priority = 100
        count = 0
        run = self.env['quickbooks.migration.run'].create({
            'company_id': self.company_id.id,
            'mode': self.mode,
            'state': 'planning' if self.mode == 'dry_run' else 'running',
        })
        probe_by_area = {
            probe.area: probe for probe in self.env['quickbooks.data.probe'].search([
                ('company_id', '=', self.company_id.id),
            ])
        }
        for entity_type in ordered_entities:
            for direction in directions:
                idempotency_key = 'migration_%s_%s_%s_%s' % (
                    run.id, entity_type, direction, self.company_id.id,
                )
                step = self.env['quickbooks.migration.run.step'].create({
                    'run_id': run.id,
                    'sequence': 100 - priority,
                    'entity_type': entity_type,
                    'direction': direction,
                    'status': 'pending',
                    'expected_count': self._expected_count(entity_type, probe_by_area),
                    'idempotency_key': idempotency_key,
                })
                if self.mode == 'live':
                    engine.enqueue_full_entity_sync(
                        config, entity_type, direction, priority=priority,
                    )
                    step.status = 'queued'
                else:
                    step.status = 'skipped'
                count += 1
            priority -= 5

        # Sales-document relink synthetic step. Always queued (live) /
        # planned (dry-run) when any sales doc was imported, since the
        # parent / child resolution must run after every per-record
        # pull has settled — including out-of-order CDC arrivals.
        sales_doc_imports = {
            'estimate', 'invoice', 'credit_memo',
            'sales_receipt', 'refund_receipt',
        } & set(ordered_entities)
        if sales_doc_imports and self.direction in ('import', 'both'):
            relink_step = self.env['quickbooks.migration.run.step'].create({
                'run_id': run.id,
                'sequence': 100 - (priority - 5),
                'entity_type': 'sales_doc_relink',
                'direction': 'pull',
                'status': 'pending',
                'idempotency_key': 'migration_%s_sales_doc_relink_%s' % (
                    run.id, self.company_id.id,
                ),
            })
            if self.mode == 'live':
                try:
                    counters = self.env['qb.sales.doc.relinker'].relink_all(
                        config, run=run,
                    )
                    relink_step.write({
                        'status': 'completed',
                        'actual_count': sum(c['imported'] for c in counters.values()),
                        'linked_count': sum(c['linked'] for c in counters.values()),
                        'orphan_link_count': sum(c['orphan'] for c in counters.values()),
                    })
                except Exception as exc:
                    _logger.exception('Sales-doc relinker failed')
                    relink_step.write({
                        'status': 'failed',
                        'error_message': str(exc),
                    })
            else:
                relink_step.status = 'skipped'
            count += 1

        if self.mode == 'dry_run':
            run.write({
                'state': 'completed',
                'finished_at': fields.Datetime.now(),
                'summary': '%d migration steps planned. No jobs were queued.' % count,
            })

        if self.migrate_opening_balances and self.direction in ('import', 'both'):
            if self.mode == 'live':
                try:
                    self._prepare_opening_balance_source_data(config)
                    opening_wizard = self.env['qb.post.opening.balances.wizard'].with_context(
                        default_company_id=self.company_id.id,
                        default_dry_run=False,
                    ).create({
                        'company_id': self.company_id.id,
                        'dry_run': False,
                    })
                    opening_action = opening_wizard.action_post_opening_balances()
                    if opening_action:
                        return opening_action
                except UserError as exc:
                    _logger.warning(
                        'QuickBooks opening balance auto-post skipped: %s',
                        exc,
                    )
                    return self._notification(
                        'QuickBooks Migration',
                        '%d jobs queued, but opening balances were not posted: %s'
                        % (count, exc),
                        'warning',
                        sticky=True,
                    )
            action = self.env.ref(
                'quickbooks_api_connector.action_qb_post_opening_balances_wizard',
            ).read()[0]
            action['context'] = {
                'default_company_id': self.company_id.id,
                'default_dry_run': True,
            }
            return action

        return self._notification(
            'QuickBooks Migration',
            (
                '%d migration %s. Entities will sync in dependency order.'
            ) % (
                count,
                'steps planned; no jobs queued' if self.mode == 'dry_run' else 'jobs queued',
            ),
            'success',
            sticky=True,
        )

    def _prepare_opening_balance_source_data(self, config):
        client = self.env['qb.api.client'].get_client(config)
        if self.migrate_accounts:
            self.env['qb.sync.accounts'].pull_all(client, config, 'account')
        self.env['qb.sync.reports'].pull_all(client, config, 'report')

    def _notification(self, title, message, notification_type, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': sticky,
            },
        }

    def _expected_count(self, entity_type, probe_by_area):
        area_map = {
            'recurring_transaction': 'recurring_transactions',
            'product': 'inventory_items',
            'project': 'projects',
            'time_activity': 'time_activities',
            'expense': 'expenses',
            'purchase_order': 'purchase_orders',
            'estimate': 'estimates',
            'credit_memo': 'credit_memos',
            'sales_receipt': 'sales_receipts',
            'refund_receipt': 'refund_receipts',
            'attachment': 'attachments',
            'class': 'classes',
            'department': 'departments',
            'custom_field_definition': 'custom_field_definitions',
        }
        probe = probe_by_area.get(area_map.get(entity_type, ''))
        return probe.sample_count if probe else 0
