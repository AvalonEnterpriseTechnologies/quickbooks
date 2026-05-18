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
    qb_pay_schedule_record_id = fields.Many2one(
        'hr.payroll.structure',
        string='QB Pay Schedule',
        ondelete='set null',
        copy=False,
        help='Odoo payroll structure created from the QuickBooks pay schedule '
             'referenced by qb_pay_schedule_id.',
    )
    qb_work_location_id = fields.Char(
        string='QB Work Location ID', index=True, copy=False, tracking=True,
    )
    qb_employment_status = fields.Char(string='QB Employment Status', copy=False)
    qb_rate = fields.Float(
        string='QB Rate',
        copy=False,
        help='Rate as reported by QBO Payroll. Interpretation depends on '
             'qb_rate_type (hourly = $/hour, salary = $/period, commission = %).',
    )
    qb_rate_type = fields.Selection(
        [
            ('hourly', 'Hourly'),
            ('salary', 'Salary'),
            ('commission', 'Commission'),
        ],
        string='QB Rate Type',
        copy=False,
    )
    qb_default_hours_per_week = fields.Float(
        string='QB Default Hours / Week',
        copy=False,
    )
    qb_last_synced = fields.Datetime(
        string='Last QB Sync', copy=False, tracking=True,
    )
    qb_do_not_sync = fields.Boolean(
        string='Exclude from QB Sync', default=False, tracking=True,
    )
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False, tracking=True)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
