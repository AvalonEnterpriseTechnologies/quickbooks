import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

OPTIONAL_MODULES = {
    'sale': 'Sales',
    'purchase': 'Purchase',
    'project': 'Projects',
    'hr': 'Employees (HR)',
    'hr_expense': 'Expenses',
    'hr_timesheet': 'Timesheets',
    'stock': 'Inventory',
}

# Maps each sync toggle to the Odoo module(s) it requires.
# When the user enables a toggle, any missing modules are installed automatically.
TOGGLE_REQUIRED_MODULES = {
    'qb_sync_estimates': ['sale'],
    'qb_sync_sales_receipts': ['sale'],
    'qb_sync_purchase_orders': ['purchase'],
    'qb_sync_expenses': ['hr_expense'],
    'qb_sync_employees': ['hr'],
    'qb_sync_departments': ['hr'],
    'qb_sync_time_activities': ['hr_timesheet'],
    'qb_sync_projects': ['project'],
    'qb_sync_inventory_qty': ['stock'],
    'qb_sync_inventory_adjustments': ['stock'],
    'qb_sync_inventory_valuation_accounts': ['stock'],
    'qb_payroll_enabled': ['hr'],
    'qb_payroll_create_draft_payslips': ['hr_payroll'],
    'qb_time_enabled': ['hr_timesheet'],
}


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
    qb_oauth_redirect_uri = fields.Char(
        string='OAuth Redirect URI',
        compute='_compute_qb_oauth_redirect_uri',
        readonly=True,
    )
    qb_webhook_endpoint_url = fields.Char(
        related='qb_config_id.webhook_endpoint_url',
        readonly=True,
    )

    qb_client_id = fields.Char(
        string='Client ID', groups='base.group_system',
    )
    qb_client_secret = fields.Char(
        string='Client Secret', groups='base.group_system',
    )
    qb_environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        string='Environment', default='sandbox',
    )
    qb_webhook_verifier_token = fields.Char(
        string='Webhook Verifier Token', groups='base.group_system',
    )

    qb_conflict_resolution = fields.Selection(
        [('last_modified', 'Last Modified Wins'),
         ('odoo_wins', 'Odoo Always Wins'),
         ('qbo_wins', 'QuickBooks Always Wins'),
         ('manual', 'Manual Review')],
        string='Conflict Resolution', default='odoo_wins',
    )
    qb_verify_after_push = fields.Boolean(string='Verify QBO After Push', default=True)
    qb_match_by_name = fields.Boolean(string='Allow Name-Based Matching', default=False)
    qb_auto_sync_interval = fields.Integer(
        string='Auto Sync Interval', default=30,
    )
    qb_auto_sync_interval_type = fields.Selection(
        [('seconds', 'Seconds'),
         ('minutes', 'Minutes'),
         ('hours', 'Hours'),
         ('days', 'Days')],
        string='Interval Unit', default='minutes',
    )

    # --- Accounting entity toggles (on by default) ---
    qb_sync_customers = fields.Boolean(string='Sync Customers', default=True)
    qb_sync_vendors = fields.Boolean(string='Sync Vendors', default=True)
    qb_sync_products = fields.Boolean(string='Sync Products', default=True)
    qb_sync_invoices = fields.Boolean(string='Sync Invoices', default=True)
    qb_sync_bills = fields.Boolean(string='Sync Bills', default=True)
    qb_sync_payments = fields.Boolean(string='Sync Payments', default=True)
    qb_sync_journal_entries = fields.Boolean(string='Sync Journal Entries', default=True)
    qb_sync_credit_memos = fields.Boolean(string='Sync Credit Memos', default=True)
    qb_sync_estimates = fields.Boolean(string='Sync Estimates', default=True)
    qb_sync_tax_codes = fields.Boolean(string='Sync Tax Codes', default=True)

    # --- Extended entity toggles (on by default) ---
    qb_sync_purchase_orders = fields.Boolean(string='Sync Purchase Orders', default=True)
    qb_sync_sales_receipts = fields.Boolean(string='Sync Sales Receipts', default=True)
    qb_sync_expenses = fields.Boolean(string='Sync Expenses', default=True)
    qb_sync_deposits = fields.Boolean(string='Sync Deposits', default=True)
    qb_sync_transfers = fields.Boolean(string='Sync Transfers', default=True)
    qb_sync_employees = fields.Boolean(string='Sync Employees', default=True)
    qb_sync_departments = fields.Boolean(string='Sync Departments', default=True)
    qb_sync_time_activities = fields.Boolean(string='Sync Time Activities', default=True)
    qb_sync_projects = fields.Boolean(string='Sync Projects', default=True)
    qb_sync_classes = fields.Boolean(string='Sync Classes', default=True)
    qb_sync_terms = fields.Boolean(string='Sync Payment Terms', default=True)
    qb_sync_attachments = fields.Boolean(string='Sync Attachments', default=False)
    qb_sync_inventory_qty = fields.Boolean(string='Sync Inventory Quantities', default=True)
    qb_sync_inventory_adjustments = fields.Boolean(
        string='Sync Inventory Adjustments', default=True,
    )
    qb_sync_inventory_valuation_accounts = fields.Boolean(
        string='Sync Inventory Valuation Accounts', default=True,
    )
    qb_default_warehouse_id = fields.Integer(string='Default Inventory Warehouse ID')
    qb_sync_vendor_credits = fields.Boolean(string='Sync Vendor Credits', default=True)
    qb_sync_refund_receipts = fields.Boolean(string='Sync Refund Receipts', default=True)

    # --- Payroll API (Phase 3) ---
    qb_payroll_enabled = fields.Boolean(string='Enable Payroll Sync', default=False)
    qb_payroll_create_draft_payslips = fields.Boolean(
        string='Create Draft Payslips From Payroll Checks', default=False,
    )

    # --- QuickBooks Time / TSheets API (Phase 4) ---
    qb_time_enabled = fields.Boolean(string='Enable QuickBooks Time Sync', default=False)

    # --- Optional module detection ---
    qb_mod_sale = fields.Boolean(compute='_compute_qb_module_status')
    qb_mod_purchase = fields.Boolean(compute='_compute_qb_module_status')
    qb_mod_hr = fields.Boolean(compute='_compute_qb_module_status')
    qb_mod_hr_expense = fields.Boolean(compute='_compute_qb_module_status')
    qb_mod_hr_timesheet = fields.Boolean(compute='_compute_qb_module_status')
    qb_mod_stock = fields.Boolean(compute='_compute_qb_module_status')
    qb_mod_project = fields.Boolean(compute='_compute_qb_module_status')

    def _compute_qb_config_id(self):
        Config = self.env['quickbooks.config']
        for rec in self:
            rec.qb_config_id = Config.search(
                [('company_id', '=', rec.company_id.id)], limit=1,
            )

    def _compute_qb_oauth_redirect_uri(self):
        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        ).rstrip('/')
        for rec in self:
            rec.qb_oauth_redirect_uri = (
                '%s/qb/oauth/callback' % base_url if base_url else False
            )

    @api.depends_context('uid')
    def _compute_qb_module_status(self):
        IrModule = self.env['ir.module.module'].sudo()
        status = {}
        for mod_name in OPTIONAL_MODULES:
            rec = IrModule.search(
                [('name', '=', mod_name), ('state', '=', 'installed')],
                limit=1,
            )
            status[mod_name] = bool(rec)
        for rec in self:
            rec.qb_mod_sale = status.get('sale', False)
            rec.qb_mod_purchase = status.get('purchase', False)
            rec.qb_mod_project = status.get('project', False)
            rec.qb_mod_hr = status.get('hr', False)
            rec.qb_mod_hr_expense = status.get('hr_expense', False)
            rec.qb_mod_hr_timesheet = status.get('hr_timesheet', False)
            rec.qb_mod_stock = status.get('stock', False)

    # --- Module install actions ---

    def _install_module(self, module_name):
        module = self.env['ir.module.module'].sudo().search(
            [('name', '=', module_name)], limit=1,
        )
        if not module:
            raise UserError(
                'Module "%s" not found. Check your Odoo addons path.' % module_name
            )
        if module.state != 'installed':
            module.button_immediate_install()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_install_sale(self):
        return self._install_module('sale')

    def action_install_purchase(self):
        return self._install_module('purchase')

    def action_install_project(self):
        return self._install_module('project')

    def action_install_hr(self):
        return self._install_module('hr')

    def action_install_hr_expense(self):
        return self._install_module('hr_expense')

    def action_install_hr_timesheet(self):
        return self._install_module('hr_timesheet')

    def action_install_stock(self):
        return self._install_module('stock')

    # --- Config persistence ---

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
                'qb_verify_after_push': getattr(config, 'verify_after_push', True),
                'qb_match_by_name': getattr(config, 'match_by_name', False),
                'qb_auto_sync_interval': config.auto_sync_interval,
                'qb_auto_sync_interval_type': getattr(
                    config, 'auto_sync_interval_type', 'minutes',
                ),
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
                'qb_sync_purchase_orders': getattr(config, 'sync_purchase_orders', True),
                'qb_sync_sales_receipts': getattr(config, 'sync_sales_receipts', True),
                'qb_sync_expenses': getattr(config, 'sync_expenses', True),
                'qb_sync_deposits': getattr(config, 'sync_deposits', True),
                'qb_sync_transfers': getattr(config, 'sync_transfers', True),
                'qb_sync_employees': getattr(config, 'sync_employees', True),
                'qb_sync_departments': getattr(config, 'sync_departments', True),
                'qb_sync_time_activities': getattr(config, 'sync_time_activities', True),
                'qb_sync_projects': getattr(config, 'sync_projects', True),
                'qb_sync_classes': getattr(config, 'sync_classes', True),
                'qb_sync_terms': getattr(config, 'sync_terms', True),
                'qb_sync_attachments': getattr(config, 'sync_attachments', False),
                'qb_sync_inventory_qty': getattr(config, 'sync_inventory_qty', True),
                'qb_sync_inventory_adjustments': getattr(
                    config, 'sync_inventory_adjustments', True,
                ),
                'qb_sync_inventory_valuation_accounts': getattr(
                    config, 'sync_inventory_valuation_accounts', True,
                ),
                'qb_default_warehouse_id': getattr(
                    config, 'qb_default_warehouse_id', False,
                ) or False,
                'qb_sync_vendor_credits': getattr(config, 'sync_vendor_credits', True),
                'qb_sync_refund_receipts': getattr(config, 'sync_refund_receipts', True),
                'qb_payroll_enabled': getattr(config, 'payroll_enabled', False),
                'qb_payroll_create_draft_payslips': getattr(
                    config, 'payroll_create_draft_payslips', False,
                ),
                'qb_time_enabled': getattr(config, 'qbt_enabled', False),
            })
        return res

    def _ensure_modules_for_toggles(self):
        """Auto-install Odoo modules required by enabled sync toggles."""
        IrModule = self.env['ir.module.module'].sudo()
        needs_reload = False
        for toggle_field, mod_names in TOGGLE_REQUIRED_MODULES.items():
            if not getattr(self, toggle_field, False):
                continue
            for mod_name in mod_names:
                module = IrModule.search([('name', '=', mod_name)], limit=1)
                if module and module.state != 'installed':
                    _logger.info(
                        "Auto-installing module '%s' required by %s",
                        mod_name, toggle_field,
                    )
                    module.button_immediate_install()
                    needs_reload = True
        return needs_reload

    def _update_sync_cron(self, interval, interval_type):
        """Sync the periodic full-sync cron with user-configured interval."""
        cron = self.env.ref(
            'quickbooks_api_connector.ir_cron_qb_full_sync', raise_if_not_found=False,
        )
        if cron:
            cron.sudo().write({
                'interval_number': max(interval, 1),
                'interval_type': interval_type or 'minutes',
            })

    def set_values(self):
        super().set_values()

        needs_reload = self._ensure_modules_for_toggles()

        config = self._get_or_create_qb_config()
        interval = self.qb_auto_sync_interval or 30
        interval_type = self.qb_auto_sync_interval_type or 'minutes'

        vals = {
            'client_id': self.qb_client_id or '',
            'environment': self.qb_environment or 'sandbox',
            'webhook_verifier_token': self.qb_webhook_verifier_token or '',
            'conflict_resolution': self.qb_conflict_resolution or 'odoo_wins',
            'verify_after_push': self.qb_verify_after_push,
            'match_by_name': self.qb_match_by_name,
            'auto_sync_interval': interval,
            'auto_sync_interval_type': interval_type,
            'sync_customers': self.qb_sync_customers,
            'sync_vendors': self.qb_sync_vendors,
            'sync_products': self.qb_sync_products,
            'sync_invoices': self.qb_sync_invoices,
            'sync_bills': self.qb_sync_bills,
            'sync_payments': self.qb_sync_payments,
            'sync_journal_entries': self.qb_sync_journal_entries,
            'sync_credit_memos': self.qb_sync_credit_memos,
            'sync_estimates': self.qb_sync_estimates,
            'qb_default_warehouse_id': self.qb_default_warehouse_id or False,
        }
        if self.qb_client_secret:
            vals['client_secret'] = self.qb_client_secret

        toggle_fields = [
            'sync_tax_codes', 'sync_purchase_orders', 'sync_sales_receipts',
            'sync_expenses', 'sync_deposits', 'sync_transfers', 'sync_employees',
            'sync_departments', 'sync_time_activities', 'sync_projects',
            'sync_classes', 'sync_terms', 'sync_attachments', 'sync_inventory_qty',
            'sync_inventory_adjustments', 'sync_inventory_valuation_accounts',
            'sync_vendor_credits', 'sync_refund_receipts', 'payroll_enabled',
            'payroll_create_draft_payslips', 'qbt_enabled',
        ]
        field_map = {
            'qbt_enabled': 'qb_time_enabled',
            'payroll_enabled': 'qb_payroll_enabled',
            'payroll_create_draft_payslips': 'qb_payroll_create_draft_payslips',
        }
        for f in toggle_fields:
            settings_field = field_map.get(f, 'qb_' + f)
            if hasattr(config, f):
                vals[f] = getattr(self, settings_field, False)

        config.write(vals)
        self._update_sync_cron(interval, interval_type)

        if needs_reload:
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

    # --- Quick actions ---

    def action_qb_connect(self):
        return self.env.ref(
            'quickbooks_api_connector.action_quickbooks_setup_wizard',
        ).read()[0]

    def action_qb_validate_setup(self):
        config = self._get_or_create_qb_config()
        return config.action_validate_setup_locally()

    def action_qb_disconnect(self):
        config = self._get_or_create_qb_config()
        config.action_disconnect()

    def action_qb_test_connection(self):
        config = self._get_or_create_qb_config()
        config.action_test_connection()

    def action_qb_sync_now(self):
        config = self._get_or_create_qb_config()
        return config.action_sync_now()

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
