from odoo import fields, models


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    qb_check_id = fields.Char(string='QB Payroll Check ID', index=True, copy=False)
    qb_employee_id = fields.Char(string='QB Employee ID', index=True, copy=False)
    qb_gross_pay = fields.Monetary(
        string='QB Gross Pay', currency_field='currency_id', copy=False,
    )
    qb_net_pay = fields.Monetary(
        string='QB Net Pay', currency_field='currency_id', copy=False,
    )
    qb_status = fields.Char(string='QB Payroll Status', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_sync_error = fields.Text(string='QB Sync Error', copy=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
