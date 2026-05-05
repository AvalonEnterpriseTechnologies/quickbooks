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
    migrate_accounts = fields.Boolean(default=True, string='Chart of Accounts')
    migrate_tax_codes = fields.Boolean(default=True, string='Tax Codes')
    migrate_customers = fields.Boolean(default=True, string='Customers')
    migrate_vendors = fields.Boolean(default=True, string='Vendors')
    migrate_products = fields.Boolean(default=True, string='Products / Items')
    migrate_invoices = fields.Boolean(default=True, string='Invoices')
    migrate_bills = fields.Boolean(default=True, string='Bills')
    migrate_payments = fields.Boolean(default=True, string='Payments')
    migrate_journal_entries = fields.Boolean(default=False, string='Journal Entries')

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
        if self.migrate_tax_codes:
            ordered_entities.append('tax_code')
        if self.migrate_customers:
            ordered_entities.append('customer')
        if self.migrate_vendors:
            ordered_entities.append('vendor')
        if self.migrate_products:
            ordered_entities.append('product')
        if self.migrate_invoices:
            ordered_entities.append('invoice')
        if self.migrate_bills:
            ordered_entities.append('bill')
        if self.migrate_payments:
            ordered_entities.append('payment')
            ordered_entities.append('bill_payment')
        if self.migrate_journal_entries:
            ordered_entities.append('journal_entry')

        directions = []
        if self.direction in ('import', 'both'):
            directions.append('pull')
        if self.direction in ('export', 'both'):
            directions.append('push')

        priority = 100
        count = 0
        for entity_type in ordered_entities:
            for direction in directions:
                engine.enqueue_full_entity_sync(
                    config, entity_type, direction, priority=priority,
                )
                count += 1
            priority -= 5

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QuickBooks Migration',
                'message': (
                    '%d migration jobs queued. '
                    'Entities will sync in dependency order.'
                ) % count,
                'type': 'success',
                'sticky': True,
            },
        }
