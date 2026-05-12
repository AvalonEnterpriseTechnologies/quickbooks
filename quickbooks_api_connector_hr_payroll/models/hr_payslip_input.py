from odoo import fields, models


class HrPayslipInput(models.Model):
    _inherit = 'hr.payslip.input'

    qb_benefit_id = fields.Char(string='QB Benefit ID', index=True, copy=False)
    qb_employee_id = fields.Char(string='QB Employee ID', index=True, copy=False)
    qb_source_check_id = fields.Char(string='QB Source Check ID', index=True, copy=False)
    qb_benefit_type = fields.Selection(
        [
            ('health', 'Health'),
            ('retirement', 'Retirement'),
            ('garnishment', 'Garnishment'),
            ('other', 'Other'),
        ],
        string='QB Benefit Type',
        default='other',
        copy=False,
    )
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
