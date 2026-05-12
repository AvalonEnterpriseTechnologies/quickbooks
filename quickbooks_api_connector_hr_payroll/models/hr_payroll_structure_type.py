from odoo import fields, models


class HrPayrollStructureType(models.Model):
    _inherit = 'hr.payroll.structure.type'

    qb_pay_schedule_id = fields.Char(string='QB Pay Schedule ID', index=True, copy=False)
    qb_frequency = fields.Char(string='QB Frequency', copy=False)
    qb_next_pay_date = fields.Date(string='QB Next Pay Date', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
