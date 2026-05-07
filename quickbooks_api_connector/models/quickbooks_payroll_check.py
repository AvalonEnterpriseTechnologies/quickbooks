from odoo import fields, models


class QuickbooksPayrollCheck(models.Model):
    _name = 'quickbooks.payroll.check'
    _description = 'QuickBooks Payroll Check'
    _rec_name = 'display_name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    qb_check_id = fields.Char(required=True, index=True)
    qb_employee_id = fields.Char(index=True)
    odoo_employee_id = fields.Integer(string='Odoo Employee ID', index=True)
    display_name = fields.Char(required=True)
    check_date = fields.Date()
    pay_period_start = fields.Date()
    pay_period_end = fields.Date()
    gross_pay = fields.Float()
    net_pay = fields.Float()
    status = fields.Char()
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    odoo_payslip_id = fields.Integer(string='Draft Payslip ID', index=True)

    _qb_payroll_check_uniq = models.Constraint(
        'unique(company_id, qb_check_id)',
        'QuickBooks payroll checks must be unique per company.',
    )
