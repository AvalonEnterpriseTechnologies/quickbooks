from odoo import fields, models


class HrContract(models.Model):
    _inherit = 'hr.contract'

    qb_compensation_id = fields.Char(
        string='QB Compensation ID', index=True, copy=False, tracking=True,
    )
    qb_employee_id = fields.Char(
        string='QB Employee ID', index=True, copy=False, tracking=True,
    )
    qb_pay_schedule_id = fields.Char(
        string='QB Pay Schedule ID', index=True, copy=False, tracking=True,
    )
    qb_work_location_id = fields.Char(
        string='QB Work Location ID', index=True, copy=False, tracking=True,
    )
    qb_employment_status = fields.Char(string='QB Employment Status', copy=False)
    qb_last_synced = fields.Datetime(
        string='Last QB Sync', copy=False, tracking=True,
    )
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False, tracking=True,
    )
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False, tracking=True)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
