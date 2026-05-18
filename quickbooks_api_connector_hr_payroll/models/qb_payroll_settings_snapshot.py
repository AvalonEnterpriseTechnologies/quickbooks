from odoo import fields, models


class QBPayrollSettingsSnapshot(models.Model):
    """Searchable snapshot of QuickBooks Payroll settings.

    Replaces the legacy ``ir.config_parameter`` blob written by
    ``qb.sync.payroll.settings``: payload kept as Json so additions on the
    QBO side flow through without a schema bump, while company_id +
    captured_at make the snapshot first-class in Odoo.
    """

    _name = 'qb.payroll.settings.snapshot'
    _description = 'QuickBooks Payroll Settings Snapshot'
    _order = 'captured_at desc, id desc'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    captured_at = fields.Datetime(
        string='Captured At',
        default=fields.Datetime.now,
        required=True,
    )
    pay_items_json = fields.Json(string='Pay Items')
    pay_schedules_json = fields.Json(string='Pay Schedules')
    work_locations_json = fields.Json(string='Work Locations')
    workers_comp_json = fields.Json(string='Workers Comp Classes')
    raw_json = fields.Json(string='Raw Payload')
