from odoo import fields, models


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    qb_pay_schedule_id = fields.Char(
        string='QB Pay Schedule ID',
        index=True,
        copy=False,
        help='QuickBooks pay schedule ID this Odoo payroll structure mirrors. '
             'Used to find-or-create one structure per QBO pay schedule and '
             'to drive the contract -> structure link.',
    )
    qb_frequency = fields.Char(string='QB Pay Frequency', copy=False)
    qb_next_pay_date = fields.Date(string='QB Next Pay Date', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
