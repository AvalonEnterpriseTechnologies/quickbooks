from odoo import api, fields, models


class QBPayrollCheck(models.Model):
    """Read-only archive of every paycheck imported from QuickBooks Online Payroll.

    Kept separate from ``hr.payslip`` so that imported checks never collide
    with payslips Odoo will compute after the cutover, and so Odoo's payroll
    invariants (struct_id, contract_id, computed lines, payslip workflow) are
    never violated by incomplete QBO data.
    """

    _name = 'qb.payroll.check'
    _description = 'QuickBooks Payroll Check Archive'
    _order = 'check_date desc, id desc'
    _rec_name = 'display_name'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
    qb_check_id = fields.Char(
        string='QB Check ID', required=True, index=True, copy=False,
    )
    qb_employee_id = fields.Char(string='QB Employee ID', index=True, copy=False)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        ondelete='set null',
        index=True,
    )
    contract_id = fields.Many2one(
        'hr.contract',
        string='Contract',
        ondelete='set null',
    )
    display_name = fields.Char(string='Display Name', copy=False)
    check_number = fields.Char(string='Check Number', copy=False)
    check_date = fields.Date(string='Check Date', copy=False, index=True)
    period_start = fields.Date(string='Period Start', copy=False)
    period_end = fields.Date(string='Period End', copy=False)
    payment_method = fields.Selection(
        [
            ('direct_deposit', 'Direct Deposit'),
            ('check', 'Check'),
            ('cash', 'Cash'),
            ('other', 'Other'),
        ],
        string='Payment Method',
        copy=False,
    )
    status = fields.Selection(
        [
            ('draft', 'Draft'),
            ('paid', 'Paid'),
            ('void', 'Voided'),
            ('reversed', 'Reversed'),
            ('other', 'Other'),
        ],
        string='Status',
        default='paid',
        copy=False,
    )
    gross_pay = fields.Monetary(
        string='Gross Pay', currency_field='currency_id', copy=False,
    )
    net_pay = fields.Monetary(
        string='Net Pay', currency_field='currency_id', copy=False,
    )
    total_employee_tax = fields.Monetary(
        string='Total Employee Tax',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_employer_tax = fields.Monetary(
        string='Total Employer Tax',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_deductions = fields.Monetary(
        string='Total Deductions',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_employer_contributions = fields.Monetary(
        string='Total Employer Contributions',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    journal_ref_id = fields.Char(string='QB Journal Reference', copy=False)
    qb_last_synced = fields.Datetime(string='Last QB Sync', copy=False)
    qb_raw_json = fields.Json(string='QB Raw JSON', copy=False)
    ytd_json = fields.Json(string='QB YTD Snapshot', copy=False)
    line_ids = fields.One2many(
        'qb.payroll.check.line', 'check_id', string='Lines', copy=False,
    )
    archive_move_id = fields.Many2one(
        'account.move',
        string='Archive Journal Entry',
        ondelete='set null',
        copy=False,
        help='Mirror journal entry posted when '
             'qb_payroll_post_archive_journal is enabled on the QuickBooks '
             'configuration.',
    )

    _qb_check_uniq = models.Constraint(
        'unique(company_id, qb_check_id)',
        'A QuickBooks payroll check can only be archived once per company.',
    )

    @api.depends(
        'line_ids.amount',
        'line_ids.line_type',
        'line_ids.is_employer_side',
    )
    def _compute_totals(self):
        for check in self:
            emp_tax = 0.0
            er_tax = 0.0
            ded = 0.0
            er_contrib = 0.0
            for line in check.line_ids:
                amt = line.amount or 0.0
                if line.line_type == 'tax':
                    if line.is_employer_side:
                        er_tax += amt
                    else:
                        emp_tax += amt
                elif line.line_type == 'deduction':
                    if line.is_employer_side:
                        er_contrib += amt
                    else:
                        ded += amt
                elif line.line_type == 'employer_contribution':
                    er_contrib += amt
            check.total_employee_tax = emp_tax
            check.total_employer_tax = er_tax
            check.total_deductions = ded
            check.total_employer_contributions = er_contrib


class QBPayrollCheckLine(models.Model):
    """A single earnings / tax / deduction / contribution / benefit line on
    an archived QuickBooks paycheck.
    """

    _name = 'qb.payroll.check.line'
    _description = 'QuickBooks Payroll Check Line'
    _order = 'check_id, sequence, id'

    check_id = fields.Many2one(
        'qb.payroll.check', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(
        related='check_id.company_id', store=True, readonly=True,
    )
    currency_id = fields.Many2one(
        related='check_id.currency_id', readonly=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [
            ('earning', 'Earning'),
            ('tax', 'Tax'),
            ('deduction', 'Deduction'),
            ('employer_contribution', 'Employer Contribution'),
            ('benefit', 'Benefit'),
        ],
        required=True,
        default='earning',
    )
    is_employer_side = fields.Boolean(
        string='Employer Side',
        default=False,
        help='True if this row is an employer-paid amount (employer tax, '
             'employer contribution, or employer share of a benefit).',
    )
    qb_pay_item_id = fields.Char(string='QB Pay Item ID', index=True)
    salary_rule_id = fields.Many2one(
        'hr.salary.rule',
        string='Matched Salary Rule',
        ondelete='set null',
    )
    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    qb_tax_type = fields.Char(string='QB Tax Type')
    qb_tax_jurisdiction = fields.Char(string='QB Jurisdiction')
    qb_benefit_type = fields.Selection(
        [
            ('health', 'Health'),
            ('retirement', 'Retirement'),
            ('garnishment', 'Garnishment'),
            ('other', 'Other'),
        ],
        string='QB Benefit Type',
    )
    hours = fields.Float(string='Hours')
    rate = fields.Float(string='Rate')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    is_pre_tax = fields.Boolean(string='Pre-Tax')
    qb_raw_json = fields.Json(string='QB Raw JSON')
