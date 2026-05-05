import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QuickbooksSetupWizard(models.TransientModel):
    _name = 'quickbooks.setup.wizard'
    _description = 'QuickBooks Setup Wizard'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    environment = fields.Selection(
        [('sandbox', 'Development (Sandbox)'), ('production', 'Production')],
        default='sandbox', required=True,
    )
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)
    oauth_redirect_uri = fields.Char(
        string='OAuth Redirect URI',
        compute='_compute_oauth_redirect_uri',
        help='Add this exact URI to the Intuit Developer Portal Redirect URIs '
             'before connecting.',
    )
    webhook_endpoint_url = fields.Char(
        string='Odoo Webhook URL',
        compute='_compute_webhook_endpoint_url',
        help='Paste this URL into the Intuit Developer Portal under '
             'Webhooks. Intuit will return a Verifier Token to paste into '
             'Settings > QuickBooks after you finish connecting.',
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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company_id = res.get('company_id') or self.env.company.id
        config = self.env['quickbooks.config'].search([
            ('company_id', '=', company_id),
        ], limit=1)
        if config:
            res.update({
                'company_id': config.company_id.id,
                'environment': config.environment,
                'client_id': config.client_id,
                'client_secret': config.client_secret,
            })
        return res

    def _save_config(self):
        self.ensure_one()
        Config = self.env['quickbooks.config']
        config = Config.search([
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        vals = {
            'company_id': self.company_id.id,
            'environment': self.environment,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }
        if config:
            config.write(vals)
        else:
            config = Config.create(vals)
        return config

    def action_save_credentials(self):
        """Save credentials without leaving Odoo for the Intuit OAuth flow."""
        self._save_config()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks credentials saved',
                'message': (
                    'Add the OAuth Redirect URI to Intuit, then click '
                    'Connect to QuickBooks.'
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_test_setup_locally(self):
        """Save credentials and validate local setup without opening Intuit."""
        config = self._save_config()
        return config.action_validate_setup_locally()

    def action_save_and_connect(self):
        """Create or update the QB config, then initiate OAuth flow."""
        config = self._save_config()
        return config.action_connect_qb()
