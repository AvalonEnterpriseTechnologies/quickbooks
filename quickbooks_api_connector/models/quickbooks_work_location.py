from odoo import fields, models


class QuickbooksWorkLocation(models.Model):
    _name = 'quickbooks.work.location'
    _description = 'QuickBooks Employee Work Location'
    _rec_name = 'name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    qb_work_location_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    line1 = fields.Char()
    city = fields.Char()
    state_code = fields.Char()
    postal_code = fields.Char()
    country = fields.Char()
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)

    _qb_work_location_uniq = models.Constraint(
        'unique(company_id, qb_work_location_id)',
        'QuickBooks work locations must be unique per company.',
    )
