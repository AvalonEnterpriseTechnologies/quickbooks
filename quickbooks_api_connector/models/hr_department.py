from odoo import api, fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    qb_department_id = fields.Char(string='QB Department ID', index=True, copy=False)
    qb_sync_token = fields.Char(string='QB Sync Token', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
