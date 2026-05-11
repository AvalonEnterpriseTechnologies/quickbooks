from odoo import fields, models


class QuickbooksEmployeeBenefit(models.Model):
    _name = 'quickbooks.employee.benefit'
    _description = 'QuickBooks Employee Benefit / Deduction'
    _order = 'period_end desc, employee_name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    employee_id = fields.Many2one('hr.employee', ondelete='set null')
    qb_employee_id = fields.Char(index=True)
    employee_name = fields.Char()
    benefit_type = fields.Selection(
        [
            ('health', 'Health'),
            ('retirement', 'Retirement'),
            ('garnishment', 'Garnishment'),
            ('other', 'Other'),
        ],
        default='other',
        required=True,
    )
    name = fields.Char(required=True)
    amount = fields.Monetary(currency_field='currency_id')
    period_start = fields.Date(index=True)
    period_end = fields.Date(index=True)
    source_check_id = fields.Char(index=True)
    raw_json = fields.Json()
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )

    _benefit_source_uniq = models.Constraint(
        'unique(company_id, source_check_id, qb_employee_id, name, amount)',
        'This QuickBooks benefit/deduction line has already been imported.',
    )
