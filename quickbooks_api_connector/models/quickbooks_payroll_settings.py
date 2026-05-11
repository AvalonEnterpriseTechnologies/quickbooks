from odoo import fields, models


class QuickbooksPayrollSettings(models.Model):
    _name = 'quickbooks.payroll.settings'
    _description = 'QuickBooks Payroll Settings Snapshot'
    _order = 'fetched_at desc'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        ondelete='cascade',
    )
    fetched_at = fields.Datetime(default=fields.Datetime.now, required=True)
    pay_items_json = fields.Json()
    pay_schedules_json = fields.Json()
    work_locations_json = fields.Json()
    unsupported_notes = fields.Text(
        default=(
            'QBO public APIs do not expose full payroll tax setup, PTO policies, '
            'benefit enrollment definitions, garnishment orders, or agency setup '
            'as writable/readable settings resources for general integrations.'
        ),
    )
