from odoo import fields, models


class HrPayrollStructureType(models.Model):
    _inherit = 'hr.payroll.structure.type'

    qb_pay_schedule_id = fields.Char(
        string='QB Legacy Pay Schedule ID',
        index=True,
        copy=False,
        help='Retained for backward compatibility with pre-19.0.2.0 installs '
             'that stored the pay schedule ID on the structure type. New code '
             'paths store it on hr.payroll.structure instead.',
    )
    qb_frequency = fields.Char(
        string='QB Frequency',
        copy=False,
        help='Pay frequency category (WEEKLY, BIWEEKLY, SEMIMONTHLY, MONTHLY). '
             'Multiple pay schedules can share the same structure type when '
             'their frequency matches.',
    )
    qb_next_pay_date = fields.Date(string='QB Next Pay Date', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
