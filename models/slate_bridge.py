import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TaskSyncManagerQB(models.AbstractModel):
    """Extend SLATE task sync manager with QuickBooks trigger support."""
    _inherit = 'task.sync.manager'

    def _trigger_quickbooks_sync(self, entity_type, payload):
        try:
            config = self.env['quickbooks.config'].get_config()
            engine = self.env['qb.sync.engine']
            if entity_type:
                engine.enqueue_full_entity_sync(
                    config, entity_type,
                    payload.get('direction', 'pull'),
                )
            else:
                engine.run_full_sync(config)
        except Exception:
            _logger.exception('QuickBooks sync trigger failed')


class IntegrationRegistryQB(models.Model):
    """Extend SLATE integration registry with QuickBooks credential fields."""
    _inherit = 'slate.integration.registry'

    qb_client_id = fields.Char(
        'Client ID', compute='_compute_qb_config_fields',
        inverse='_inverse_qb_credentials', store=False,
    )
    qb_client_secret = fields.Char(
        'Client Secret', compute='_compute_qb_config_fields',
        inverse='_inverse_qb_credentials', store=False,
        groups='quickbooks_api_module.group_qb_manager',
    )
    qb_environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('production', 'Production'),
    ], string='Environment', compute='_compute_qb_config_fields',
        inverse='_inverse_qb_credentials', store=False,
    )
    qb_webhook_verifier_token = fields.Char(
        'Webhook Verifier Token', compute='_compute_qb_config_fields',
        inverse='_inverse_qb_credentials', store=False,
        groups='quickbooks_api_module.group_qb_manager',
    )

    def _compute_qb_config_fields(self):
        for rec in self:
            if rec.provider == 'quickbooks':
                config = rec._get_config_record() if rec.config_model else None
                if config:
                    rec.qb_client_id = config.client_id if hasattr(config, 'client_id') else False
                    rec.qb_client_secret = config.client_secret if hasattr(config, 'client_secret') else False
                    rec.qb_environment = config.environment if hasattr(config, 'environment') else False
                    rec.qb_webhook_verifier_token = (
                        config.webhook_verifier_token if hasattr(config, 'webhook_verifier_token') else False
                    )
                    continue
            rec.qb_client_id = False
            rec.qb_client_secret = False
            rec.qb_environment = False
            rec.qb_webhook_verifier_token = False

    def _inverse_qb_credentials(self):
        for rec in self.filtered(lambda r: r.provider == 'quickbooks'):
            config = rec._get_config_record()
            vals = {}
            if rec.qb_client_id:
                vals['client_id'] = rec.qb_client_id
            if rec.qb_client_secret:
                vals['client_secret'] = rec.qb_client_secret
            if rec.qb_environment:
                vals['environment'] = rec.qb_environment
            if rec.qb_webhook_verifier_token:
                vals['webhook_verifier_token'] = rec.qb_webhook_verifier_token
            if not vals:
                continue
            if config:
                config.sudo().write(vals)
            else:
                vals.setdefault('client_id', vals.get('client_id', ''))
                self.env['quickbooks.config'].sudo().create(vals)
