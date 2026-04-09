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
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        default='sandbox', required=True,
    )
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)
    webhook_verifier_token = fields.Char(string='Webhook Verifier Token')

    def action_save_and_connect(self):
        """Create or update the QB config, then initiate OAuth flow."""
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
            'webhook_verifier_token': self.webhook_verifier_token,
        }
        if config:
            config.write(vals)
        else:
            config = Config.create(vals)

        return config.action_connect_qb()
