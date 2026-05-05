from odoo import fields, models


class QuickbooksPayrollEmployee(models.Model):
    _name = 'quickbooks.payroll.employee'
    _description = 'QuickBooks Payroll Employee'
    _rec_name = 'display_name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    qb_employee_id = fields.Char(required=True, index=True)
    odoo_employee_id = fields.Integer(string='Odoo Employee ID', index=True)
    display_name = fields.Char(required=True)
    employment_status = fields.Char()
    work_location_id = fields.Char(string='QB Work Location ID')
    pay_schedule_id = fields.Char(string='QB Pay Schedule ID')
    hire_date = fields.Date()
    termination_date = fields.Date()
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)

    _qb_payroll_employee_uniq = models.Constraint(
        'unique(company_id, qb_employee_id)',
        'QuickBooks payroll employee records must be unique per company.',
    )
