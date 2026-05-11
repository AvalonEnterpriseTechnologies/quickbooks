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
    migrate_invoices = fields.Boolean(default=True, string='Invoices')
    migrate_bills = fields.Boolean(default=True, string='Bills')
    migrate_payments = fields.Boolean(default=True, string='Payments')
    migrate_journal_entries = fields.Boolean(default=False, string='Journal Entries')
    migrate_inventory_adjustments = fields.Boolean(
        default=False, string='Inventory Adjustments',
    )
    migrate_payroll = fields.Boolean(default=False, string='Payroll Read Data')
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
        if self.migrate_invoices:
            ordered_entities.append('invoice')
        if self.migrate_bills:
            ordered_entities.append('bill')
        if self.migrate_payments:
            ordered_entities.append('payment')
            ordered_entities.append('bill_payment')
        if self.migrate_journal_entries:
            ordered_entities.append('journal_entry')
        if self.migrate_inventory_adjustments:
            ordered_entities.append('inventory_adjustment')
        if self.migrate_payroll:
            ordered_entities.extend([
                'payroll_employee', 'payroll_compensation', 'payroll_pay_item',
                'payroll_schedule', 'payroll_check', 'work_location',
            ])
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

        if self.mode == 'dry_run':
            run.write({
                'state': 'completed',
                'finished_at': fields.Datetime.now(),
                'summary': '%d migration steps planned. No jobs were queued.' % count,
            })

        if self.migrate_opening_balances and self.direction in ('import', 'both'):
            action = self.env.ref(
                'quickbooks_api_connector.action_qb_post_opening_balances_wizard',
            ).read()[0]
            action['context'] = {
                'default_company_id': self.company_id.id,
                'default_dry_run': True,
            }
            return action

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Migration',
                'message': (
                    '%d migration %s. Entities will sync in dependency order.'
                ) % (
                    count,
                    'steps planned; no jobs queued' if self.mode == 'dry_run' else 'jobs queued',
                ),
                'type': 'success',
                'sticky': True,
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
            'sales_receipt': 'sales_receipts',
            'attachment': 'attachments',
            'class': 'classes',
            'department': 'departments',
            'custom_field_definition': 'custom_field_definitions',
        }
        probe = probe_by_area.get(area_map.get(entity_type, ''))
        return probe.sample_count if probe else 0
