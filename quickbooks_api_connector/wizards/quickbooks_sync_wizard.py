import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QuickbooksSyncWizard(models.TransientModel):
    _name = 'quickbooks.sync.wizard'
    _description = 'QuickBooks Manual Sync Wizard'

    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    sync_direction = fields.Selection(
        [('both', 'Bidirectional'),
         ('push', 'Odoo → QuickBooks'),
         ('pull', 'QuickBooks → Odoo')],
        default='both', required=True,
    )
    sync_customers = fields.Boolean(default=True)
    sync_vendors = fields.Boolean(default=True)
    sync_products = fields.Boolean(default=True)
    sync_invoices = fields.Boolean(default=True)
    sync_bills = fields.Boolean(default=True)
    sync_payments = fields.Boolean(default=True)
    sync_journal_entries = fields.Boolean(default=True)
    sync_credit_memos = fields.Boolean(default=True)

    def action_run_sync(self):
        """Queue sync jobs for the selected entities."""
        self.ensure_one()
        config = self.env['quickbooks.config'].get_config(self.company_id)
        if config.state != 'connected':
            raise UserError('QuickBooks is not connected for this company.')

        engine = self.env['qb.sync.engine']
        entity_flags = [
            ('customer', self.sync_customers),
            ('vendor', self.sync_vendors),
            ('product', self.sync_products),
            ('invoice', self.sync_invoices),
            ('bill', self.sync_bills),
            ('payment', self.sync_payments),
            ('bill_payment', self.sync_payments),
            ('journal_entry', self.sync_journal_entries),
            ('credit_memo', self.sync_credit_memos),
        ]
        directions = []
        if self.sync_direction in ('both', 'push'):
            directions.append('push')
        if self.sync_direction in ('both', 'pull'):
            directions.append('pull')

        count = 0
        for entity_type, enabled in entity_flags:
            if not enabled:
                continue
            for direction in directions:
                engine.enqueue_full_entity_sync(
                    config, entity_type, direction,
                )
                count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Sync',
                'message': '%d sync jobs queued.' % count,
                'type': 'success',
                'sticky': False,
            },
        }
