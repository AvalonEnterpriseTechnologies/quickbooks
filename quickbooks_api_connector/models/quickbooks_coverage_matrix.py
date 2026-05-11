from odoo import api, fields, models


class QuickbooksCoverageMatrix(models.Model):
    _name = 'quickbooks.coverage.matrix'
    _description = 'QuickBooks Coverage Matrix'
    _order = 'area'

    area = fields.Char(required=True, index=True)
    entity_type = fields.Char(index=True)
    status = fields.Selection(
        [
            ('full', 'Full'),
            ('partial', 'Partial'),
            ('manual', 'Manual'),
            ('unsupported', 'Unsupported'),
        ],
        default='partial',
        required=True,
    )
    notes = fields.Text()

    @api.model
    def refresh_from_registry(self):
        from ..services.qb_sync_engine import ENTITY_SERVICE_MAP

        for entity_type in sorted(ENTITY_SERVICE_MAP):
            existing = self.search([('entity_type', '=', entity_type)], limit=1)
            vals = {
                'area': entity_type.replace('_', ' ').title(),
                'entity_type': entity_type,
                'status': 'full',
                'notes': 'Registered sync service: %s' % ENTITY_SERVICE_MAP[entity_type],
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
        manual_rows = {
            'Workers Compensation': 'Manual class/rate mirror; report snapshots only.',
            'HR Advisor': 'Manual document store; no public Intuit API.',
            'Bank Rules': 'Manual Odoo-side mirror; no public QBO BankRule API.',
        }
        for area, notes in manual_rows.items():
            existing = self.search([('area', '=', area)], limit=1)
            vals = {'area': area, 'status': 'manual', 'notes': notes}
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
