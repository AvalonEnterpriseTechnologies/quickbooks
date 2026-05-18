import base64
import hashlib
import logging
import urllib.parse
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
    granted_scopes = fields.Char(
        string='Granted OAuth Scopes',
        readonly=True,
        help='Space-separated OAuth scopes last granted by Intuit.',
    )
    subscription_tier = fields.Selection(
        [
            ('simple_start', 'Simple Start'),
            ('essentials', 'Essentials'),
            ('plus', 'Plus'),
            ('advanced', 'Advanced'),
            ('unknown', 'Unknown'),
        ],
        string='QuickBooks Subscription Tier',
        default='unknown',
        readonly=True,
    )
    tier_supports_classes = fields.Boolean(
        string='Supports Classes', readonly=True,
    )
    tier_supports_custom_fields = fields.Boolean(
        string='Supports Custom Fields', readonly=True,
    )
    tier_supports_inventory = fields.Boolean(
        string='Supports Inventory', readonly=True,
    )
    payroll_subscription_active = fields.Boolean(
        string='Payroll Subscription Active', readonly=True,
    )
    access_token_encrypted = fields.Text(copy=False)
    refresh_token_encrypted = fields.Text(copy=False)
    token_expiry = fields.Datetime(string='Token Expiry')
    refresh_token_expiry = fields.Datetime(string='Refresh Token Expiry')
    environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        default='sandbox', required=True,
    )
    oauth_redirect_uri = fields.Char(
        string='OAuth Redirect URI',
        compute='_compute_oauth_redirect_uri',
        help='Add this exact URI to the Intuit Developer Portal Redirect URIs '
             'before connecting.',
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
    sync_reports = fields.Boolean(default=False, string='Sync Financial Reports')
    sync_recurring_transactions = fields.Boolean(
        default=False,
        string='Sync Recurring Transactions',
    )
    custom_fields_enabled = fields.Boolean(
        default=False,
        string='Sync Custom Fields',
    )
    sync_employee_benefits = fields.Boolean(
        default=False,
        string='Sync Employee Benefits',
    )
    sync_payroll_settings = fields.Boolean(
        default=False,
        string='Sync Payroll Settings',
    )
    reports_method = fields.Selection(
        [('Accrual', 'Accrual'), ('Cash', 'Cash')],
        default='Accrual',
        string='Reports Accounting Method',
    )
    reports_accounting_methods = fields.Selection(
        [
            ('default', 'Use Reports Accounting Method'),
            ('accrual', 'Accrual Only'),
            ('cash', 'Cash Only'),
            ('both', 'Accrual and Cash'),
        ],
        default='default',
        string='Report Methods To Pull',
    )
    reports_window_strategy = fields.Selection(
        [
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('six_month', 'Six Month'),
        ],
        default='monthly',
        string='Report Window Strategy',
    )
    reports_history_months = fields.Integer(
        default=12,
        string='Reports History Months',
    )
    reports_keep_n = fields.Integer(
        default=12,
        string='Report Snapshots To Keep',
    )
    reports_use_v2_now = fields.Boolean(
        default=False,
        string='Use Modernized Reports Parser',
    )
    balance_variance_threshold = fields.Monetary(
        string='Balance Variance Threshold',
        default=0.01,
        currency_field='company_currency_id',
    )
    company_currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )

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
    account_name_strategy = fields.Selection(
        [
            ('keep_odoo', 'Keep Odoo Account Names'),
            ('prefer_qbo', 'Prefer QuickBooks For Empty/Generic Names'),
            ('mirror_qbo', 'Mirror QuickBooks Account Names'),
        ],
        default='keep_odoo',
        string='Account Name Strategy',
        help='Controls how QBO account names update an existing Odoo chart of accounts.',
    )
    account_strategy = fields.Selection(
        [
            ('map_only', 'Map Only (Never Create)'),
            ('create_missing', 'Create Missing Accounts From QBO'),
        ],
        default='map_only',
        required=True,
        string='Chart Of Accounts Strategy',
        help='map_only keeps the existing Odoo chart of accounts intact: QBO '
             'accounts are linked to existing Odoo accounts by code, '
             'compatible code, name, or compatible name, and rows that fail '
             'to match are logged for manual mapping instead of being '
             'created. create_missing falls back to creating a new Odoo '
             'account whenever no match is found.',
    )
    qb_account_last_discovery = fields.Datetime(
        string='Last QBO Account Discovery',
        readonly=True,
        copy=False,
    )
    qb_account_discovered_count = fields.Integer(
        string='QBO Accounts Discovered',
        readonly=True,
        copy=False,
    )
    qb_account_mapped_count = fields.Integer(
        string='QBO Accounts Mapped To Odoo',
        readonly=True,
        copy=False,
    )
    qb_account_unmapped_count = fields.Integer(
        string='QBO Accounts Unmapped',
        readonly=True,
        copy=False,
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

    def _compute_oauth_redirect_uri(self):
        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        ).rstrip('/')
        for rec in self:
            rec.oauth_redirect_uri = (
                '%s/qb/oauth/callback' % base_url if base_url else False
            )

    def _compute_webhook_endpoint_url(self):
        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        ).rstrip('/')
        for rec in self:
            rec.webhook_endpoint_url = (
                '%s/qb/webhook' % base_url if base_url else False
            )

    def _get_public_base_url(self):
        return (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        ).rstrip('/')

    @staticmethod
    def _is_local_url(url):
        host = (urllib.parse.urlparse(url).hostname or '').lower()
        return host in ('localhost', '127.0.0.1', '::1')

    def validate_setup_locally(self):
        """Validate Odoo-side QuickBooks setup without calling a QBO company API."""
        self.ensure_one()
        errors = []

        if not self.client_id:
            errors.append('Client ID is missing.')
        if not self.client_secret_encrypted or not self.client_secret:
            errors.append('Client Secret is missing or cannot be decrypted.')
        if self.environment not in ('sandbox', 'production'):
            errors.append('Environment must be Development (Sandbox) or Production.')

        base_url = self._get_public_base_url()
        if not base_url:
            errors.append('Odoo Base URL (web.base.url) is not configured.')
        elif not base_url.startswith('https://') and not self._is_local_url(base_url):
            errors.append(
                'Odoo Base URL must use HTTPS for Intuit OAuth. Current value: %s'
                % base_url
            )

        if not self.oauth_redirect_uri:
            errors.append('OAuth Redirect URI could not be generated.')
        if not self.webhook_endpoint_url:
            errors.append('Webhook URL could not be generated.')

        if errors:
            raise UserError('\n'.join(errors))

        auth_service = self.env['qb.auth.service']
        auth_params = {
            'client_id': self.client_id,
            'scope': auth_service._get_scopes(self),
            'redirect_uri': self.oauth_redirect_uri,
            'response_type': 'code',
            'state': 'local_validation',
        }
        authorization_url = '%s?%s' % (
            'https://appcenter.intuit.com/connect/oauth2',
            urllib.parse.urlencode(auth_params),
        )
        api_base_url = auth_service.get_api_base_url(self)
        return {
            'oauth_redirect_uri': self.oauth_redirect_uri,
            'webhook_endpoint_url': self.webhook_endpoint_url,
            'authorization_url': authorization_url,
            'api_base_url': api_base_url,
        }

    def action_validate_setup_locally(self):
        self.ensure_one()
        result = self.validate_setup_locally()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks setup looks ready',
                'message': (
                    'Odoo can save/decrypt the credentials and generate the '
                    'OAuth Redirect URI and Webhook URL. Copy the OAuth '
                    'Redirect URI into Intuit before connecting. API base: %s'
                    % result['api_base_url']
                ),
                'type': 'success',
                'sticky': True,
            },
        }

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

    def set_tokens(self, access_token, refresh_token, expires_in=3600, scope=None):
        self.ensure_one()
        vals = {
            'access_token_encrypted': self._encrypt(access_token),
            'refresh_token_encrypted': self._encrypt(refresh_token),
            'token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
            'refresh_token_expiry': (
                fields.Datetime.now() + timedelta(days=100)
            ),
            'state': 'connected',
            'error_message': False,
        }
        if scope is not None:
            vals['granted_scopes'] = scope
        self.write(vals)

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
        """Always land on the standard Settings panel.

        The QuickBooks block on ``res.config.settings`` collects credentials,
        runs the OAuth handshake, exposes sync toggles, and surfaces live
        counters. There is no separate setup wizard to fall back to.
        """
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

    def action_run_pending_jobs_now(self):
        self.ensure_one()
        if self.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')
        Queue = self.env['quickbooks.sync.queue']
        pending_domain = [
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'pending'),
        ]
        pending = Queue.search_count(pending_domain)
        Queue.search(pending_domain, limit=50).process_pending_jobs()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Queue',
                'message': '%d pending job(s) were sent to the queue processor.' % pending,
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

    def action_preview_qbo_accounts(self):
        """Fetch the QBO chart of accounts and report planned matches without writing.

        Posts a summary message to the config's chatter and updates the
        discovery counters so operators can review what map_only will link,
        what it will leave unmapped (requiring manual mapping), and what
        create_missing would create, BEFORE the actual sync runs.
        """
        self.ensure_one()
        if self.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')
        return self._run_account_discovery(write_links=False)

    def action_apply_qbo_account_mapping(self):
        """Fetch the QBO chart of accounts and link existing Odoo accounts by code/name.

        Never creates new Odoo accounts. Use this after Preview to commit the
        suggested links onto the existing Odoo chart of accounts.
        """
        self.ensure_one()
        if self.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')
        return self._run_account_discovery(write_links=True)

    def _run_account_discovery(self, write_links):
        client = self.env['qb.api.client'].get_client(self)
        matcher = self.env['qb.record.matcher']
        try:
            records = client.query_all('Account', where_clause='Active IN (true, false)')
        except Exception as exc:
            _logger.exception('QBO account discovery failed for company %s',
                              self.company_id.name)
            raise UserError('Failed to fetch the QuickBooks chart of accounts: %s' % exc)

        matched = []
        unmatched = []
        already_linked = []
        for qb_data in records:
            qb_id = str(qb_data.get('Id') or '')
            qb_name = qb_data.get('Name') or ''
            qb_code = (qb_data.get('AcctNum') or '').strip()
            existing, decision = matcher.find_odoo_match_for_account(
                qb_data, self.company_id, return_reason=True,
            )
            if existing and decision == 'linked_by_id':
                already_linked.append((qb_id, qb_code, qb_name, existing, decision))
            elif existing:
                matched.append((qb_id, qb_code, qb_name, existing, decision))
                if write_links and not existing.qb_account_id:
                    matcher.link_odoo_record(existing, 'account', qb_data)
                    if hasattr(existing, '_record_qb_link_decision'):
                        existing.sudo()._record_qb_link_decision(
                            self, qb_data, decision,
                        )
            else:
                unmatched.append((qb_id, qb_code, qb_name))

        self.write({
            'qb_account_last_discovery': fields.Datetime.now(),
            'qb_account_discovered_count': len(records),
            'qb_account_mapped_count': len(already_linked) + len(matched),
            'qb_account_unmapped_count': len(unmatched),
        })
        self._post_account_discovery_summary(
            records, matched, unmatched, already_linked, write_links,
        )
        action_label = 'applied' if write_links else 'previewed'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Chart Of Accounts Discovery',
                'message': (
                    'Discovery %s: %d QBO accounts, %d already linked, '
                    '%d newly mapped, %d unmapped (require manual mapping).'
                ) % (
                    action_label, len(records),
                    len(already_linked), len(matched), len(unmatched),
                ),
                'type': 'success' if not unmatched else 'warning',
                'sticky': True,
            },
        }

    def _post_account_discovery_summary(self, records, matched, unmatched,
                                        already_linked, write_links):
        verb = 'Applied' if write_links else 'Preview'
        body_lines = [
            '<b>QuickBooks Chart Of Accounts Discovery — %s</b>' % verb,
            '<ul>',
            '<li>%d QBO accounts read from realm %s</li>' % (
                len(records), self.realm_id or '',
            ),
            '<li>%d already linked to Odoo (qb_account_id set)</li>' % len(already_linked),
            '<li>%d %s mapped to existing Odoo accounts</li>' % (
                len(matched), 'newly' if write_links else 'will be',
            ),
            '<li>%d unmapped — must be mapped manually before the next pull</li>' % len(
                unmatched,
            ),
            '</ul>',
        ]
        if unmatched:
            body_lines.append('<b>Unmapped QBO accounts:</b><ul>')
            for qb_id, qb_code, qb_name in unmatched[:50]:
                body_lines.append(
                    '<li>QBO ID %s — %s — %s</li>' % (qb_id, qb_code or '(no code)', qb_name),
                )
            if len(unmatched) > 50:
                body_lines.append('<li>... and %d more</li>' % (len(unmatched) - 50))
            body_lines.append('</ul>')
            body_lines.append(
                '<p>To map: open the Odoo account, paste the QBO ID into '
                '"QB Account ID", and save. Then re-run Apply to refresh '
                'the counters, or run a Sync Now to pull data using the '
                'manually mapped accounts.</p>'
            )
        self.message_post(
            body='\n'.join(body_lines),
            subject='QuickBooks Chart Of Accounts Discovery',
            subtype_xmlid='mail.mt_note',
        )
        if unmatched and write_links:
            self._raise_unmapped_account_activity(unmatched)

    def _raise_unmapped_account_activity(self, unmatched):
        manager_group = self.env.ref(
            'quickbooks_api_connector.group_qb_manager',
            raise_if_not_found=False,
        )
        responsible = self.env.user
        if manager_group:
            users = manager_group.users.filtered(lambda u: u.active)
            if users:
                responsible = users[0]
        summary = '%d QuickBooks accounts need manual mapping in Odoo' % len(unmatched)
        note = 'See the most recent chatter message on this QuickBooks ' \
               'configuration record for the full list of unmapped QBO accounts. ' \
               'Map each by pasting its QBO ID into the matching Odoo account.'
        self.activity_schedule(
            'mail.mail_activity_data_warning',
            summary=summary,
            note=note,
            user_id=responsible.id,
        )

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
