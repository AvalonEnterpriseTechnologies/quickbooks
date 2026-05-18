import logging
from datetime import timedelta

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

# Maps each sync toggle to Odoo module(s) that may be useful when QBO has data
# for the associated area. These modules are suggested to the user, never
# installed automatically.
TOGGLE_SUGGESTED_MODULES = {
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

TOGGLE_DATA_AREAS = {
    'qb_sync_estimates': ['estimates'],
    'qb_sync_sales_receipts': ['sales_receipts'],
    'qb_sync_purchase_orders': ['purchase_orders'],
    'qb_sync_expenses': ['expenses'],
    'qb_sync_time_activities': ['time_activities'],
    'qb_sync_projects': ['projects'],
    'qb_sync_inventory_qty': ['inventory_items'],
    'qb_sync_inventory_adjustments': ['inventory_items'],
    'qb_sync_inventory_valuation_accounts': ['inventory_items'],
    'qb_payroll_enabled': ['payroll_paychecks'],
    'qb_payroll_create_draft_payslips': ['payroll_paychecks'],
    'qb_time_enabled': ['time_activities'],
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
    qb_account_strategy = fields.Selection(
        [
            ('map_only', 'Map Only (Never Create)'),
            ('create_missing', 'Create Missing Accounts From QBO'),
        ],
        string='Chart Of Accounts Strategy',
        default='create_missing',
        help='create_missing brings the QBO chart of accounts into Odoo: '
             'unmatched QBO accounts are created on the fly so journal '
             'entries, bills, and payroll line resolvers always find a '
             'destination account. Switch to map_only only when an '
             'operator has hand-curated the Odoo CoA and wants every '
             'unmatched QBO account flagged for manual mapping.',
    )
    qb_auto_apply_account_mapping = fields.Boolean(
        string='Auto-Apply QBO Account Mapping On Sync',
        default=True,
        help='When on, every Sync Now also runs Apply QBO Account Mapping '
             'right after the chart of accounts is pulled, so line '
             'resolvers always find a destination Odoo account.',
    )
    qb_account_last_discovery = fields.Datetime(
        related='qb_config_id.qb_account_last_discovery', readonly=True,
    )
    qb_account_discovered_count = fields.Integer(
        related='qb_config_id.qb_account_discovered_count', readonly=True,
    )
    qb_account_mapped_count = fields.Integer(
        related='qb_config_id.qb_account_mapped_count', readonly=True,
    )
    qb_account_unmapped_count = fields.Integer(
        related='qb_config_id.qb_account_unmapped_count', readonly=True,
    )
    qb_verify_after_push = fields.Boolean(string='Verify QBO After Push', default=True)
    qb_auto_post_pulled_records = fields.Boolean(
        string='Auto-Post Pulled Records',
        default=True,
        help='Post invoices, bills, vendor credits, journal entries, and '
             'payments immediately after they are pulled from QuickBooks, '
             'so they arrive in Odoo in the same posted state they have in '
             'QBO instead of staying draft. Turn off to import everything '
             'as draft for manual review before posting.',
    )
    qb_match_by_name = fields.Boolean(string='Allow Name-Based Matching', default=True)
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
    qb_auto_push_transfers = fields.Boolean(
        string='Auto-push Transfers to QBO',
        default=False,
        help='Off during QBO -> Odoo migration. When off, transfers are '
             'pushed only when an operator clicks "Push Transfer to '
             'QuickBooks" on the journal entry.',
    )
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
    qb_sync_reports = fields.Boolean(string='Sync Financial Reports', default=False)
    qb_sync_recurring_transactions = fields.Boolean(
        string='Sync Recurring Transactions',
        default=False,
    )
    qb_custom_fields_enabled = fields.Boolean(
        string='Sync Custom Fields',
        default=False,
    )
    qb_sync_employee_benefits = fields.Boolean(
        string='Sync Employee Benefits',
        default=False,
    )
    qb_sync_payroll_settings = fields.Boolean(
        string='Sync Payroll Settings',
        default=False,
    )
    qb_reports_method = fields.Selection(
        [('Accrual', 'Accrual'), ('Cash', 'Cash')],
        string='Reports Accounting Method',
        default='Accrual',
    )
    qb_reports_history_months = fields.Integer(
        string='Reports History Months',
        default=12,
    )
    qb_reports_keep_n = fields.Integer(
        string='Report Snapshots To Keep',
        default=12,
    )
    qb_reports_use_v2_now = fields.Boolean(
        string='Use Modernized Reports Parser',
        default=False,
    )

    # --- Payroll API (Phase 3) ---
    qb_payroll_enabled = fields.Boolean(string='Enable Payroll Sync', default=False)
    qb_payroll_create_draft_payslips = fields.Boolean(
        string='Create Draft Payslips From Payroll Checks', default=False,
    )
    qb_sync_payroll_pay_schedules = fields.Boolean(
        string='Sync Pay Schedules', default=True,
    )
    qb_sync_payroll_pay_items = fields.Boolean(
        string='Sync Pay Items', default=True,
    )
    qb_sync_payroll_employees_detail = fields.Boolean(
        string='Sync Payroll Employees', default=True,
    )
    qb_sync_payroll_tax_setup = fields.Boolean(
        string='Sync Payroll Tax Setup (W-4 / state)', default=True,
    )
    qb_sync_payroll_compensations = fields.Boolean(
        string='Sync Payroll Compensations', default=True,
    )
    qb_sync_payroll_checks_history = fields.Boolean(
        string='Sync Payroll Checks (history)', default=True,
    )
    qb_sync_payroll_payslips = fields.Boolean(
        string='Backfill Payslips From QBO Checks', default=True,
        help='When enabled (and the hr_payroll bridge is installed), every '
             'QBO paycheck is projected into hr.payslip + hr.payslip.run as '
             'a posted (done) batch so historical pay runs show up in Odoo '
             'Payroll. Idempotent on qb_check_id.',
    )
    qb_payroll_post_archive_journal = fields.Boolean(
        string='Post Archive Journal Per QBO Paycheck',
        default=False,
    )
    qb_payroll_archived = fields.Boolean(
        string='QuickBooks Payroll Archived',
        related='qb_config_id.qb_payroll_archived',
        readonly=True,
    )
    qb_payroll_cutover_date = fields.Datetime(
        string='QuickBooks Payroll Cutover Date',
        related='qb_config_id.qb_payroll_cutover_date',
        readonly=True,
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

    # --- Live counters (replace the standalone Dashboard view) ---
    qb_queue_depth = fields.Integer(
        string='Pending Sync Jobs', compute='_compute_qb_metrics',
    )
    qb_failed_queue_count = fields.Integer(
        string='Failed Sync Jobs', compute='_compute_qb_metrics',
    )
    qb_sync_errors_24h = fields.Integer(
        string='Sync Errors (24h)', compute='_compute_qb_metrics',
    )
    qb_sync_success_24h = fields.Integer(
        string='Sync Successes (24h)', compute='_compute_qb_metrics',
    )
    qb_last_successful_sync = fields.Datetime(
        string='Last Success From Sync Log', compute='_compute_qb_metrics',
    )
    qb_coverage_summary = fields.Text(
        string='QuickBooks Coverage', compute='_compute_qb_coverage_summary',
        help='Read-only summary of every QBO entity this connector supports. '
             'Generated from the live sync engine registry plus any manual '
             'coverage rows.',
    )
    qb_sales_doc_integrity_summary = fields.Text(
        string='Sales Document Migration Integrity',
        compute='_compute_qb_sales_doc_integrity_summary',
        help='Per-sales-doc summary from the most recent migration run: '
             'imported / linked / orphan counts and QBO-vs-Odoo totals for '
             'Estimates, Invoices, Credit Memos, Sales Receipts, and Refund '
             'Receipts. Refreshed by qb.sales.doc.relinker at the end of '
             'every Initial Migration run.',
    )

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

    def _compute_qb_metrics(self):
        Queue = self.env['quickbooks.sync.queue'].sudo()
        Log = self.env['quickbooks.sync.log'].sudo()
        since = fields.Datetime.now() - timedelta(days=1)
        for rec in self:
            domain = [('company_id', '=', rec.company_id.id)]
            rec.qb_queue_depth = Queue.search_count(
                domain + [('state', 'in', ('pending', 'processing'))],
            )
            rec.qb_failed_queue_count = Queue.search_count(
                domain + [('state', '=', 'failed')],
            )
            rec.qb_sync_errors_24h = Log.search_count(
                domain + [('state', '=', 'error'), ('create_date', '>=', since)],
            )
            rec.qb_sync_success_24h = Log.search_count(
                domain + [('state', '=', 'success'), ('create_date', '>=', since)],
            )
            last = Log.search(
                domain + [('state', '=', 'success')], limit=1,
            )
            rec.qb_last_successful_sync = last.create_date if last else False

    def _compute_qb_coverage_summary(self):
        Matrix = self.env['quickbooks.coverage.matrix'].sudo()
        rows = Matrix.search([], order='area asc')
        if not rows:
            try:
                Matrix.refresh_from_registry()
                rows = Matrix.search([], order='area asc')
            except Exception:
                rows = Matrix.browse()
        summary = '\n'.join(
            '%-30s %-10s %s' % (
                (row.area or '')[:30],
                (row.status or '').upper(),
                row.notes or '',
            )
            for row in rows
        )
        for rec in self:
            rec.qb_coverage_summary = summary

    def _compute_qb_sales_doc_integrity_summary(self):
        """Latest qb.sales.doc.relinker counters formatted as a fixed-width table."""
        Step = self.env['quickbooks.migration.run.step'].sudo()
        Run = self.env['quickbooks.migration.run'].sudo()
        sales_entities = (
            'estimate', 'invoice', 'credit_memo',
            'sales_receipt', 'refund_receipt',
        )
        for rec in self:
            run = Run.search(
                [('company_id', '=', rec.company_id.id)],
                order='started_at desc', limit=1,
            )
            if not run:
                rec.qb_sales_doc_integrity_summary = (
                    'No migration runs yet. Open the Initial Migration '
                    'wizard to import QuickBooks sales documents.'
                )
                continue
            lines = [
                '%-15s %8s %8s %8s %15s %15s' % (
                    'Type', 'Pulled', 'Linked', 'Orphan', 'QBO Total', 'Odoo Total',
                ),
                '-' * 75,
            ]
            any_step = False
            for entity in sales_entities:
                step = Step.search([
                    ('run_id', '=', run.id),
                    ('entity_type', '=', entity),
                    ('direction', '=', 'pull'),
                ], order='id desc', limit=1)
                if not step:
                    continue
                any_step = True
                lines.append(
                    '%-15s %8d %8d %8d %15.2f %15.2f' % (
                        entity,
                        step.actual_count or 0,
                        step.linked_count or 0,
                        step.orphan_link_count or 0,
                        step.amount_total_qbo or 0.0,
                        step.amount_total_odoo or 0.0,
                    )
                )
            if not any_step:
                rec.qb_sales_doc_integrity_summary = (
                    'Last migration run %s did not include any sales-document '
                    'imports.'
                ) % run.started_at
            else:
                rec.qb_sales_doc_integrity_summary = '\n'.join(lines)

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
                'qb_auto_post_pulled_records': getattr(
                    config, 'auto_post_pulled_records', True,
                ),
                'qb_match_by_name': getattr(config, 'match_by_name', True),
                'qb_account_strategy': getattr(
                    config, 'account_strategy', 'create_missing',
                ),
                'qb_auto_apply_account_mapping': getattr(
                    config, 'qb_auto_apply_account_mapping', True,
                ),
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
                'qb_auto_push_transfers': getattr(
                    config, 'qb_auto_push_transfers', False,
                ),
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
                'qb_sync_reports': getattr(config, 'sync_reports', False),
                'qb_sync_recurring_transactions': getattr(
                    config, 'sync_recurring_transactions', False,
                ),
                'qb_custom_fields_enabled': getattr(
                    config, 'custom_fields_enabled', False,
                ),
                'qb_sync_employee_benefits': getattr(
                    config, 'sync_employee_benefits', False,
                ),
                'qb_sync_payroll_settings': getattr(
                    config, 'sync_payroll_settings', False,
                ),
                'qb_reports_method': getattr(config, 'reports_method', 'Accrual'),
                'qb_reports_history_months': getattr(
                    config, 'reports_history_months', 12,
                ),
                'qb_reports_keep_n': getattr(config, 'reports_keep_n', 12),
                'qb_reports_use_v2_now': getattr(config, 'reports_use_v2_now', False),
                'qb_payroll_enabled': getattr(config, 'payroll_enabled', False),
                'qb_payroll_create_draft_payslips': getattr(
                    config, 'payroll_create_draft_payslips', False,
                ),
                'qb_sync_payroll_pay_schedules': getattr(
                    config, 'sync_payroll_pay_schedules', True,
                ),
                'qb_sync_payroll_pay_items': getattr(
                    config, 'sync_payroll_pay_items', True,
                ),
                'qb_sync_payroll_employees_detail': getattr(
                    config, 'sync_payroll_employees', True,
                ),
                'qb_sync_payroll_tax_setup': getattr(
                    config, 'sync_payroll_tax_setup', True,
                ),
                'qb_sync_payroll_compensations': getattr(
                    config, 'sync_payroll_compensations', True,
                ),
                'qb_sync_payroll_checks_history': getattr(
                    config, 'sync_payroll_checks', True,
                ),
                'qb_sync_payroll_payslips': getattr(
                    config, 'sync_payroll_payslips', True,
                ),
                'qb_payroll_post_archive_journal': getattr(
                    config, 'qb_payroll_post_archive_journal', False,
                ),
                'qb_time_enabled': getattr(config, 'qbt_enabled', False),
            })
        return res

    def _suggest_modules_for_toggles(self):
        """Return missing optional modules implied by enabled sync toggles.

        The connector must not install addons just because a toggle was enabled.
        Module installs are explicit user actions, ideally after qb.data.probe
        confirms there is QBO data for that area.
        """
        IrModule = self.env['ir.module.module'].sudo()
        suggestions = set()
        for toggle_field, mod_names in TOGGLE_SUGGESTED_MODULES.items():
            if not getattr(self, toggle_field, False):
                continue
            if not self._toggle_has_qbo_data(toggle_field):
                continue
            for mod_name in mod_names:
                module = IrModule.search([('name', '=', mod_name)], limit=1)
                if module and module.state != 'installed':
                    suggestions.add(mod_name)
        return sorted(suggestions)

    def _toggle_has_qbo_data(self, toggle_field):
        areas = TOGGLE_DATA_AREAS.get(toggle_field)
        if not areas:
            return False
        config = self._get_or_create_qb_config()
        probes = self.env['quickbooks.data.probe'].sudo().search([
            ('company_id', '=', config.company_id.id),
            ('area', 'in', areas),
            ('has_data', '=', True),
        ], limit=1)
        return bool(probes)

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

        suggested_modules = self._suggest_modules_for_toggles()

        config = self._get_or_create_qb_config()
        interval = self.qb_auto_sync_interval or 30
        interval_type = self.qb_auto_sync_interval_type or 'minutes'

        vals = {
            'client_id': self.qb_client_id or '',
            'environment': self.qb_environment or 'sandbox',
            'webhook_verifier_token': self.qb_webhook_verifier_token or '',
            'conflict_resolution': self.qb_conflict_resolution or 'odoo_wins',
            'verify_after_push': self.qb_verify_after_push,
            'auto_post_pulled_records': self.qb_auto_post_pulled_records,
            'match_by_name': self.qb_match_by_name,
            'account_strategy': self.qb_account_strategy or 'create_missing',
            'qb_auto_apply_account_mapping': self.qb_auto_apply_account_mapping,
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
            'sync_expenses', 'sync_deposits', 'sync_transfers',
            'qb_auto_push_transfers',
            'sync_employees',
            'sync_departments', 'sync_time_activities', 'sync_projects',
            'sync_classes', 'sync_terms', 'sync_attachments', 'sync_inventory_qty',
            'sync_inventory_adjustments', 'sync_inventory_valuation_accounts',
            'sync_vendor_credits', 'sync_refund_receipts', 'payroll_enabled',
            'sync_reports', 'reports_method', 'reports_history_months',
            'reports_keep_n', 'reports_use_v2_now',
            'sync_recurring_transactions', 'custom_fields_enabled',
            'sync_employee_benefits', 'sync_payroll_settings', 'payroll_enabled',
            'payroll_create_draft_payslips', 'qbt_enabled',
            'sync_payroll_pay_schedules', 'sync_payroll_pay_items',
            'sync_payroll_tax_setup', 'sync_payroll_compensations',
            'sync_payroll_checks', 'sync_payroll_payslips',
            'qb_payroll_post_archive_journal',
        ]
        field_map = {
            'qbt_enabled': 'qb_time_enabled',
            'payroll_enabled': 'qb_payroll_enabled',
            'payroll_create_draft_payslips': 'qb_payroll_create_draft_payslips',
            'reports_method': 'qb_reports_method',
            'reports_history_months': 'qb_reports_history_months',
            'reports_keep_n': 'qb_reports_keep_n',
            'reports_use_v2_now': 'qb_reports_use_v2_now',
            'custom_fields_enabled': 'qb_custom_fields_enabled',
            'sync_payroll_pay_schedules': 'qb_sync_payroll_pay_schedules',
            'sync_payroll_pay_items': 'qb_sync_payroll_pay_items',
            'sync_payroll_employees': 'qb_sync_payroll_employees_detail',
            'sync_payroll_tax_setup': 'qb_sync_payroll_tax_setup',
            'sync_payroll_compensations': 'qb_sync_payroll_compensations',
            'sync_payroll_checks': 'qb_sync_payroll_checks_history',
            'sync_payroll_payslips': 'qb_sync_payroll_payslips',
            'qb_payroll_post_archive_journal': 'qb_payroll_post_archive_journal',
            'qb_auto_push_transfers': 'qb_auto_push_transfers',
        }
        for f in toggle_fields:
            settings_field = field_map.get(f, 'qb_' + f)
            if hasattr(config, f):
                vals[f] = getattr(self, settings_field, False)

        config.write(vals)
        self._update_sync_cron(interval, interval_type)

        if suggested_modules:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Optional Odoo modules not installed',
                    'message': (
                        'QuickBooks settings were saved. These optional modules '
                        'may be useful if QBO has related data: %s. Install them '
                        'manually only when needed.'
                    ) % ', '.join(suggested_modules),
                    'type': 'warning',
                    'sticky': True,
                },
            }

    # --- Quick actions ---

    def action_qb_connect(self):
        """Save credentials inline and start the OAuth handshake.

        Replaces the standalone setup wizard. Credentials must already be
        entered in this settings panel (Client ID + Client Secret +
        Environment) before the user clicks Connect.
        """
        self.ensure_one()
        if not self.qb_client_id or not self.qb_client_secret:
            raise UserError(
                'Enter the Client ID and Client Secret above before '
                'connecting to QuickBooks.'
            )
        self.set_values()
        config = self._get_or_create_qb_config()
        return config.action_connect_qb()

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

    def action_qb_run_pending_jobs_now(self):
        config = self._get_or_create_qb_config()
        return config.action_run_pending_jobs_now()

    def action_qb_preview_accounts(self):
        """Pull the QBO chart of accounts and post a discovery summary.

        No Odoo accounts are written. Use after Connect to confirm what
        the map_only strategy will and won't be able to link before
        running the actual sync.
        """
        config = self._get_or_create_qb_config()
        return config.action_preview_qbo_accounts()

    def action_qb_apply_account_mapping(self):
        """Pull the QBO CoA and link matched accounts onto the existing Odoo CoA.

        Never creates new Odoo accounts. Unmapped QBO accounts raise a
        warning activity for the QuickBooks Manager group.
        """
        config = self._get_or_create_qb_config()
        return config.action_apply_qbo_account_mapping()

    def action_qb_enable_payroll_all(self):
        """Install Odoo payroll modules and enable every QBO payroll feature."""
        config = self._get_or_create_qb_config()
        return config.action_qb_enable_payroll_all()

    def action_qb_cutover_payroll(self):
        """Run the payroll cutover audit + flip via quickbooks.config."""
        config = self._get_or_create_qb_config()
        return config.action_qb_cutover_payroll()

    def action_qb_payroll_audit_only(self):
        """Run only the pre-cutover audit and post results to the chatter."""
        config = self._get_or_create_qb_config()
        return config.action_qb_payroll_audit_only()

    def action_qb_run_initial_migration(self):
        """Queue a full bidirectional initial migration in dependency order.

        Functionally equivalent to the old Initial Migration wizard, but
        runs from a single Settings button. Uses the existing migration
        orchestration (``quickbooks.migration.wizard``) as a headless
        backend service so the audit trail (``quickbooks.migration.run``)
        is preserved.
        """
        self.ensure_one()
        config = self._get_or_create_qb_config()
        if config.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')
        wizard = self.env['quickbooks.migration.wizard'].create({
            'company_id': self.company_id.id,
            'direction': 'both',
            'mode': 'live',
        })
        return wizard.action_start_migration()
