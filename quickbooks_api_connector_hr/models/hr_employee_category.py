from odoo import fields, models


class HrEmployeeCategory(models.Model):
    _inherit = 'hr.employee.category'

    qb_workers_comp_code = fields.Char(string='QB Workers Comp Code', index=True, copy=False)
    qb_jurisdiction = fields.Char(string='QB Jurisdiction', copy=False)
    qb_workers_comp_rate = fields.Float(string='QB Workers Comp Rate', copy=False)
    qb_workers_comp_source = fields.Selection(
        [('manual', 'Manual'), ('report', 'QBO Report Snapshot')],
        string='QB Workers Comp Source',
        default='manual',
        copy=False,
    )
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
