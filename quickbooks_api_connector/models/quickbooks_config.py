import base64
import hashlib
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

FERNET_KEY_PARAM = 'qb_integration.fernet_key'

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
    _logger.info(
        'cryptography library not installed. '
        'Token encryption will use base64 fallback (less secure). '
        'Install with: pip install cryptography'
    )


class QuickbooksConfig(models.Model):
    _name = 'quickbooks.config'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'QuickBooks Online Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    client_id = fields.Char(string='Client ID', required=True)
    client_secret_encrypted = fields.Text(
        string='Client Secret (encrypted)', copy=False,
    )
    client_secret = fields.Char(
        string='Client Secret', store=False,
        inverse='_inverse_client_secret',
        compute='_compute_client_secret',
    )
    realm_id = fields.Char(string='Realm ID (Company ID)')
    qb_company_name = fields.Char(string='QB Company Name', readonly=True)
    access_token_encrypted = fields.Text(copy=False)
    refresh_token_encrypted = fields.Text(copy=False)
    token_expiry = fields.Datetime(string='Token Expiry')
    refresh_token_expiry = fields.Datetime(string='Refresh Token Expiry')
    environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        default='sandbox', required=True,
    )
    webhook_verifier_token = fields.Char(string='Webhook Verifier Token')
    webhook_endpoint_url = fields.Char(
        string='Webhook Endpoint URL',
        compute='_compute_webhook_endpoint_url',
        help='Paste this URL into the Intuit Developer Portal under '
             'Webhooks. Intuit will return a Verifier Token to paste below.',
    )
    oauth_state = fields.Char(string='OAuth State', copy=False, readonly=True)
    state = fields.Selection(
        [('draft', 'Not Connected'),
         ('connected', 'Connected'),
         ('error', 'Error')],
        default='draft', required=True, copy=False,
    )
    last_sync_date = fields.Datetime(string='Last Successful Sync', readonly=True)
    error_message = fields.Text(string='Last Error', readonly=True)

    sync_customers = fields.Boolean(default=True, string='Sync Customers')
    sync_vendors = fields.Boolean(default=True, string='Sync Vendors')
    sync_products = fields.Boolean(default=True, string='Sync Products')
    sync_invoices = fields.Boolean(default=True, string='Sync Invoices')
    sync_bills = fields.Boolean(default=True, string='Sync Bills')
    sync_payments = fields.Boolean(default=True, string='Sync Payments')
    sync_journal_entries = fields.Boolean(default=True, string='Sync Journal Entries')
    sync_credit_memos = fields.Boolean(default=True, string='Sync Credit Memos')
    sync_estimates = fields.Boolean(default=True, string='Sync Estimates')
    sync_tax_codes = fields.Boolean(default=True, string='Sync Tax Codes')
    sync_purchase_orders = fields.Boolean(default=True, string='Sync Purchase Orders')
    sync_sales_receipts = fields.Boolean(default=True, string='Sync Sales Receipts')
    sync_expenses = fields.Boolean(default=True, string='Sync Expenses')
    sync_deposits = fields.Boolean(default=True, string='Sync Deposits')
    sync_transfers = fields.Boolean(default=True, string='Sync Transfers')
    sync_employees = fields.Boolean(default=True, string='Sync Employees')
    sync_departments = fields.Boolean(default=True, string='Sync Departments')
    sync_time_activities = fields.Boolean(default=True, string='Sync Time Activities')
    sync_projects = fields.Boolean(default=True, string='Sync Projects')
    sync_classes = fields.Boolean(default=True, string='Sync Classes')
    sync_terms = fields.Boolean(default=True, string='Sync Payment Terms')
    sync_attachments = fields.Boolean(default=False, string='Sync Attachments')
    sync_inventory_qty = fields.Boolean(default=True, string='Sync Inventory Quantities')
    sync_inventory_adjustments = fields.Boolean(
        default=True, string='Sync Inventory Adjustments',
    )
    sync_inventory_valuation_accounts = fields.Boolean(
        default=True, string='Sync Inventory Valuation Accounts',
    )
    qb_default_warehouse_id = fields.Integer(string='Default Inventory Warehouse ID')
    sync_vendor_credits = fields.Boolean(default=True, string='Sync Vendor Credits')
    sync_refund_receipts = fields.Boolean(default=True, string='Sync Refund Receipts')

    payroll_enabled = fields.Boolean(default=False, string='Enable Payroll API')
    payroll_create_draft_payslips = fields.Boolean(
        default=False,
        string='Create Draft Payslips From Payroll Checks',
        help='When hr_payroll is installed, create draft Odoo payslips from pulled QBO payroll checks.',
    )
    qbt_enabled = fields.Boolean(default=False, string='Enable QuickBooks Time API')
    qbt_access_token_encrypted = fields.Text(copy=False)
    qbt_refresh_token_encrypted = fields.Text(copy=False)

    conflict_resolution = fields.Selection(
        [('last_modified', 'Last Modified Wins'),
         ('odoo_wins', 'Odoo Always Wins'),
         ('qbo_wins', 'QuickBooks Always Wins'),
         ('manual', 'Manual Review')],
        default='odoo_wins', required=True,
    )
    verify_after_push = fields.Boolean(
        string='Verify QBO After Push',
        default=True,
        help='Read the QBO record after push and log a warning if key fields drift.',
    )
    match_by_name = fields.Boolean(
        string='Allow Name-Based Matching',
        default=False,
        help='Use exact normalized names as a final deduplication fallback.',
    )
    auto_sync_interval = fields.Integer(
        string='Auto Sync Interval', default=30,
    )
    auto_sync_interval_type = fields.Selection(
        [('seconds', 'Seconds'),
         ('minutes', 'Minutes'),
         ('hours', 'Hours'),
         ('days', 'Days')],
        string='Interval Unit', default='minutes', required=True,
    )

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one QuickBooks configuration per company is allowed.',
    )

    def _compute_webhook_endpoint_url(self):
        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        ).rstrip('/')
        for rec in self:
            rec.webhook_endpoint_url = (
                '%s/qb/webhook' % base_url if base_url else False
            )

    def _get_fernet(self):
        if Fernet is None:
            return None
        param = self.env['ir.config_parameter'].sudo()
        key = param.get_param(FERNET_KEY_PARAM)
        if not key:
            key = Fernet.generate_key().decode()
            param.set_param(FERNET_KEY_PARAM, key)
        return Fernet(key.encode() if isinstance(key, str) else key)

    def _encrypt(self, plaintext):
        if not plaintext:
            return False
        fernet = self._get_fernet()
        if fernet:
            return fernet.encrypt(plaintext.encode()).decode()
        return base64.b64encode(plaintext.encode()).decode()

    def _decrypt(self, ciphertext):
        if not ciphertext:
            return False
        fernet = self._get_fernet()
        if fernet:
            try:
                return fernet.decrypt(ciphertext.encode()).decode()
            except Exception:
                pass
        try:
            return base64.b64decode(ciphertext.encode()).decode()
        except Exception:
            _logger.warning('Failed to decrypt QuickBooks token')
            return False

    def _inverse_client_secret(self):
        for rec in self:
            rec.client_secret_encrypted = rec._encrypt(rec.client_secret)

    @api.depends('client_secret_encrypted')
    def _compute_client_secret(self):
        for rec in self:
            rec.client_secret = rec._decrypt(rec.client_secret_encrypted)

    def get_access_token(self):
        self.ensure_one()
        return self._decrypt(self.access_token_encrypted)

    def get_refresh_token(self):
        self.ensure_one()
        return self._decrypt(self.refresh_token_encrypted)

    def set_tokens(self, access_token, refresh_token, expires_in=3600):
        self.ensure_one()
        self.write({
            'access_token_encrypted': self._encrypt(access_token),
            'refresh_token_encrypted': self._encrypt(refresh_token),
            'token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
            'refresh_token_expiry': (
                fields.Datetime.now() + timedelta(days=100)
            ),
            'state': 'connected',
            'error_message': False,
        })

    def is_token_expired(self):
        self.ensure_one()
        if not self.token_expiry:
            return True
        return fields.Datetime.now() >= self.token_expiry - timedelta(minutes=5)

    def action_connect_qb(self):
        self.ensure_one()
        auth_service = self.env['qb.auth.service']
        url = auth_service.get_authorization_url(self)
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'self',
        }

    @api.model
    def action_open_or_setup(self):
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config or not config.client_id or not config.client_secret_encrypted:
            return self.env.ref(
                'quickbooks_api_connector.action_quickbooks_setup_wizard',
            ).read()[0]
        return {
            'type': 'ir.actions.act_window',
            'name': 'QuickBooks Sync',
            'res_model': 'res.config.settings',
            'view_mode': 'form',
            'target': 'current',
            'context': {'module': 'quickbooks_api_connector'},
        }

    def action_sync_now(self):
        self.ensure_one()
        if self.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')
        self.env['qb.sync.engine'].run_full_sync(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Sync',
                'message': 'QuickBooks sync completed.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_disconnect(self):
        self.ensure_one()
        self.write({
            'access_token_encrypted': False,
            'refresh_token_encrypted': False,
            'token_expiry': False,
            'refresh_token_expiry': False,
            'realm_id': False,
            'qb_company_name': False,
            'oauth_state': False,
            'state': 'draft',
        })

    def action_test_connection(self):
        self.ensure_one()
        client = self.env['qb.api.client'].get_client(self)
        try:
            info = client.get('companyinfo/%s' % self.realm_id)
            name = info.get('CompanyInfo', {}).get('CompanyName', '')
            self.write({
                'qb_company_name': name,
                'state': 'connected',
                'error_message': False,
            })
        except Exception as e:
            self.write({'state': 'error', 'error_message': str(e)})
            raise UserError(str(e))

    def cron_refresh_tokens(self):
        configs = self.search([('state', '=', 'connected')])
        auth_service = self.env['qb.auth.service']
        for config in configs:
            try:
                auth_service.refresh_token(config)
            except Exception as e:
                _logger.error('Token refresh failed for company %s: %s',
                              config.company_id.name, e)
                config.write({'state': 'error', 'error_message': str(e)})

    @api.model
    def get_config(self, company=None):
        company = company or self.env.company
        config = self.search([('company_id', '=', company.id)], limit=1)
        if not config:
            raise UserError(
                'QuickBooks is not configured for company %s.' % company.name
            )
        return config
