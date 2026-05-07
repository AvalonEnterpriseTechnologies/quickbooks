from odoo import fields, models


class QuickbooksPayrollPayItem(models.Model):
    _name = 'quickbooks.payroll.pay.item'
    _description = 'QuickBooks Payroll Pay Item'
    _rec_name = 'name'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    qb_pay_item_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    pay_item_type = fields.Char()
    active = fields.Boolean(default=True)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)

    _qb_pay_item_uniq = models.Constraint(
        'unique(company_id, qb_pay_item_id)',
        'QuickBooks payroll pay items must be unique per company.',
    )
