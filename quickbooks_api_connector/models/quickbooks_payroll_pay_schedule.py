from odoo import fields, models


class QuickbooksPayrollPaySchedule(models.Model):
    _name = 'quickbooks.payroll.pay.schedule'
    _description = 'QuickBooks Payroll Pay Schedule'
    _rec_name = 'name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    qb_pay_schedule_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    frequency = fields.Char()
    active = fields.Boolean(default=True)
    next_pay_date = fields.Date()
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)

    _qb_pay_schedule_uniq = models.Constraint(
        'unique(company_id, qb_pay_schedule_id)',
        'QuickBooks payroll pay schedules must be unique per company.',
    )
