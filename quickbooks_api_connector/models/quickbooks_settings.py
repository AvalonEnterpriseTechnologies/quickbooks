import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # --- Delegated to quickbooks.config ---

    qb_config_id = fields.Many2one(
        'quickbooks.config', string='QuickBooks Configuration',
        compute='_compute_qb_config_id',
    )
    qb_state = fields.Selection(related='qb_config_id.state', readonly=True)
    qb_company_name = fields.Char(related='qb_config_id.qb_company_name', readonly=True)
    qb_last_sync_date = fields.Datetime(related='qb_config_id.last_sync_date', readonly=True)
    qb_realm_id = fields.Char(related='qb_config_id.realm_id', readonly=True)
    qb_error_message = fields.Text(related='qb_config_id.error_message', readonly=True)

    qb_client_id = fields.Char(string='Client ID')
    qb_client_secret = fields.Char(string='Client Secret')
    qb_environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        string='Environment', default='sandbox',
    )
    qb_webhook_verifier_token = fields.Char(string='Webhook Verifier Token')

    qb_conflict_resolution = fields.Selection(
        [('last_modified', 'Last Modified Wins'),
         ('odoo_wins', 'Odoo Always Wins'),
         ('qbo_wins', 'QuickBooks Always Wins'),
         ('manual', 'Manual Review')],
        string='Conflict Resolution', default='last_modified',
    )
    qb_auto_sync_interval = fields.Integer(
        string='Auto Sync Interval (minutes)', default=30,
    )

    # --- Accounting entity toggles ---
    qb_sync_customers = fields.Boolean(string='Sync Customers', default=True)
    qb_sync_vendors = fields.Boolean(string='Sync Vendors', default=True)
    qb_sync_products = fields.Boolean(string='Sync Products', default=True)
    qb_sync_invoices = fields.Boolean(string='Sync Invoices', default=True)
    qb_sync_bills = fields.Boolean(string='Sync Bills', default=True)
    qb_sync_payments = fields.Boolean(string='Sync Payments', default=True)
    qb_sync_journal_entries = fields.Boolean(string='Sync Journal Entries', default=True)
    qb_sync_credit_memos = fields.Boolean(string='Sync Credit Memos', default=True)
    qb_sync_estimates = fields.Boolean(string='Sync Estimates', default=False)
    qb_sync_tax_codes = fields.Boolean(string='Sync Tax Codes', default=True)

    # --- New entity toggles (Phase 2) ---
    qb_sync_purchase_orders = fields.Boolean(string='Sync Purchase Orders', default=False)
    qb_sync_sales_receipts = fields.Boolean(string='Sync Sales Receipts', default=False)
    qb_sync_expenses = fields.Boolean(string='Sync Expenses', default=False)
    qb_sync_deposits = fields.Boolean(string='Sync Deposits', default=False)
    qb_sync_transfers = fields.Boolean(string='Sync Transfers', default=False)
    qb_sync_employees = fields.Boolean(string='Sync Employees', default=False)
    qb_sync_departments = fields.Boolean(string='Sync Departments', default=False)
    qb_sync_time_activities = fields.Boolean(string='Sync Time Activities', default=False)
    qb_sync_classes = fields.Boolean(string='Sync Classes', default=False)
    qb_sync_terms = fields.Boolean(string='Sync Payment Terms', default=False)
    qb_sync_attachments = fields.Boolean(string='Sync Attachments', default=False)
    qb_sync_inventory_qty = fields.Boolean(string='Sync Inventory Quantities', default=False)
    qb_sync_vendor_credits = fields.Boolean(string='Sync Vendor Credits', default=True)
    qb_sync_refund_receipts = fields.Boolean(string='Sync Refund Receipts', default=False)

    # --- Payroll API (Phase 3) ---
    qb_payroll_enabled = fields.Boolean(string='Enable Payroll Sync', default=False)

    # --- QuickBooks Time / TSheets API (Phase 4) ---
    qb_time_enabled = fields.Boolean(string='Enable QuickBooks Time Sync', default=False)

    def _compute_qb_config_id(self):
        Config = self.env['quickbooks.config']
        for rec in self:
            rec.qb_config_id = Config.search(
                [('company_id', '=', rec.company_id.id)], limit=1,
            )

    def _get_or_create_qb_config(self):
        config = self.env['quickbooks.config'].search(
            [('company_id', '=', self.company_id.id)], limit=1,
        )
        if not config:
            config = self.env['quickbooks.config'].create({
                'company_id': self.company_id.id,
                'client_id': self.qb_client_id or '',
                'client_secret': self.qb_client_secret or '',
                'environment': self.qb_environment or 'sandbox',
            })
        return config

    @api.model
    def get_values(self):
        res = super().get_values()
        config = self.env['quickbooks.config'].search(
            [('company_id', '=', self.env.company.id)], limit=1,
        )
        if config:
            res.update({
                'qb_client_id': config.client_id,
                'qb_client_secret': config.client_secret,
                'qb_environment': config.environment,
                'qb_webhook_verifier_token': config.webhook_verifier_token,
                'qb_conflict_resolution': config.conflict_resolution,
                'qb_auto_sync_interval': config.auto_sync_interval,
                'qb_sync_customers': config.sync_customers,
                'qb_sync_vendors': config.sync_vendors,
                'qb_sync_products': config.sync_products,
                'qb_sync_invoices': config.sync_invoices,
                'qb_sync_bills': config.sync_bills,
                'qb_sync_payments': config.sync_payments,
                'qb_sync_journal_entries': config.sync_journal_entries,
                'qb_sync_credit_memos': config.sync_credit_memos,
                'qb_sync_estimates': config.sync_estimates,
                'qb_sync_tax_codes': getattr(config, 'sync_tax_codes', True),
                'qb_sync_purchase_orders': getattr(config, 'sync_purchase_orders', False),
                'qb_sync_sales_receipts': getattr(config, 'sync_sales_receipts', False),
                'qb_sync_expenses': getattr(config, 'sync_expenses', False),
                'qb_sync_deposits': getattr(config, 'sync_deposits', False),
                'qb_sync_transfers': getattr(config, 'sync_transfers', False),
                'qb_sync_employees': getattr(config, 'sync_employees', False),
                'qb_sync_departments': getattr(config, 'sync_departments', False),
                'qb_sync_time_activities': getattr(config, 'sync_time_activities', False),
                'qb_sync_classes': getattr(config, 'sync_classes', False),
                'qb_sync_terms': getattr(config, 'sync_terms', False),
                'qb_sync_attachments': getattr(config, 'sync_attachments', False),
                'qb_sync_inventory_qty': getattr(config, 'sync_inventory_qty', False),
                'qb_sync_vendor_credits': getattr(config, 'sync_vendor_credits', True),
                'qb_sync_refund_receipts': getattr(config, 'sync_refund_receipts', False),
                'qb_payroll_enabled': getattr(config, 'payroll_enabled', False),
                'qb_time_enabled': getattr(config, 'qbt_enabled', False),
            })
        return res

    def set_values(self):
        super().set_values()
        config = self._get_or_create_qb_config()
        vals = {
            'client_id': self.qb_client_id or '',
            'environment': self.qb_environment or 'sandbox',
            'webhook_verifier_token': self.qb_webhook_verifier_token or '',
            'conflict_resolution': self.qb_conflict_resolution or 'last_modified',
            'auto_sync_interval': self.qb_auto_sync_interval or 30,
            'sync_customers': self.qb_sync_customers,
            'sync_vendors': self.qb_sync_vendors,
            'sync_products': self.qb_sync_products,
            'sync_invoices': self.qb_sync_invoices,
            'sync_bills': self.qb_sync_bills,
            'sync_payments': self.qb_sync_payments,
            'sync_journal_entries': self.qb_sync_journal_entries,
            'sync_credit_memos': self.qb_sync_credit_memos,
            'sync_estimates': self.qb_sync_estimates,
        }
        if self.qb_client_secret:
            vals['client_secret'] = self.qb_client_secret

        toggle_fields = [
            'sync_tax_codes', 'sync_purchase_orders', 'sync_sales_receipts',
            'sync_expenses', 'sync_deposits', 'sync_transfers', 'sync_employees',
            'sync_departments', 'sync_time_activities', 'sync_classes', 'sync_terms',
            'sync_attachments', 'sync_inventory_qty', 'sync_vendor_credits',
            'sync_refund_receipts', 'payroll_enabled', 'qbt_enabled',
        ]
        field_map = {
            'qbt_enabled': 'qb_time_enabled',
            'payroll_enabled': 'qb_payroll_enabled',
        }
        for f in toggle_fields:
            settings_field = field_map.get(f, 'qb_' + f)
            if hasattr(config, f):
                vals[f] = getattr(self, settings_field, False)

        config.write(vals)

    def action_qb_connect(self):
        config = self._get_or_create_qb_config()
        return config.action_connect_qb()

    def action_qb_disconnect(self):
        config = self._get_or_create_qb_config()
        config.action_disconnect()

    def action_qb_test_connection(self):
        config = self._get_or_create_qb_config()
        config.action_test_connection()

    def action_open_sync_logs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Sync Logs',
            'res_model': 'quickbooks.sync.log',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_open_sync_queue(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Sync Queue',
            'res_model': 'quickbooks.sync.queue',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_open_manual_sync(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Manual Sync',
            'res_model': 'quickbooks.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_migration_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Initial Migration',
            'res_model': 'quickbooks.migration.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
