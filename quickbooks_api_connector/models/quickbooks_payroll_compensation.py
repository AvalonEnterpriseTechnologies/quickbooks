from odoo import fields, models


class QuickbooksPayrollCompensation(models.Model):
    _name = 'quickbooks.payroll.compensation'
    _description = 'QuickBooks Payroll Compensation'
    _rec_name = 'name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    qb_employee_id = fields.Char(required=True, index=True)
    odoo_employee_id = fields.Integer(string='Odoo Employee ID', index=True)
    employee_name = fields.Char(string='Employee')
    qb_compensation_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    compensation_type = fields.Char()
    active = fields.Boolean(default=True)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)

    _qb_compensation_uniq = models.Constraint(
        'unique(company_id, qb_employee_id, qb_compensation_id)',
        'QuickBooks payroll compensation records must be unique per employee.',
    )
