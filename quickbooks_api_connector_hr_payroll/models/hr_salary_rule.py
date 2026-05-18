from odoo import fields, models


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    qb_pay_item_id = fields.Char(string='QB Pay Item ID', index=True, copy=False)
    qb_pay_item_type = fields.Char(string='QB Pay Item Type', copy=False)
    qb_pay_item_category = fields.Selection(
        [
            ('earning', 'Earning'),
            ('tax', 'Tax'),
            ('deduction', 'Deduction'),
            ('employer_contribution', 'Employer Contribution'),
        ],
        string='QB Pay Item Category',
        copy=False,
    )
    qb_pay_item_calculation = fields.Selection(
        [
            ('fixed', 'Fixed Amount'),
            ('percent', 'Percent'),
            ('rate', 'Rate'),
        ],
        string='QB Pay Item Calculation',
        copy=False,
    )
    qb_pay_item_tax_jurisdiction = fields.Char(
        string='QB Tax Jurisdiction', copy=False,
    )
    qb_gl_account_id = fields.Many2one(
        'account.account',
        string='QB GL Expense Account',
        ondelete='set null',
        copy=False,
    )
    qb_liability_account_id = fields.Many2one(
        'account.account',
        string='QB GL Liability Account',
        ondelete='set null',
        copy=False,
    )
    qb_vendor_id = fields.Many2one(
        'res.partner',
        string='QB Pay Item Vendor',
        ondelete='set null',
        copy=False,
        help='Vendor (e.g. tax authority or benefits provider) tied to the '
             'pay item in QuickBooks.',
    )
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_do_not_sync = fields.Boolean(string='Exclude from QB Sync', default=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
