from odoo import fields, models


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    qb_pay_item_id = fields.Char(string='QB Pay Item ID', index=True, copy=False)
    qb_pay_item_type = fields.Char(string='QB Pay Item Type', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
