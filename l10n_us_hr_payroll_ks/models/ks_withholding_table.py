# -*- coding: utf-8 -*-
"""
Kansas withholding data models — percentage-method brackets and per-year
parameters transcribed from the KW-100 / NFC bulletin (SB 1, eff. 2024+).
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class L10nKsWithholdingBracket(models.Model):
    """Progressive marginal-rate brackets for the KS percentage method.

    Each row represents one segment of the tax table published in the KW-100
    (``whrates.pdf``) expressed in annualized terms.  The salary-rule helper
    annualizes gross pay, subtracts exemptions, then walks these rows.
    """

    _name = 'l10n.ks.withholding.bracket'
    _description = 'Kansas Withholding Tax Bracket'
    _order = 'tax_year desc, filing_status, income_from'

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True)
    tax_year = fields.Integer(required=True, index=True)

    filing_status = fields.Selection(
        [('single', 'Single / HoH / MFS'),
         ('married', 'Married filing jointly')],
        required=True,
        index=True,
    )

    income_from = fields.Float(
        string='Annualized taxable income from ($)',
        digits=(16, 2),
        required=True,
    )
    income_to = fields.Float(
        string='Annualized taxable income to ($)',
        digits=(16, 2),
        required=True,
        help='Use a very large sentinel (e.g. 999999999) for the open-ended top bracket.',
    )
    base_tax = fields.Float(
        string='Base tax ($)',
        digits=(16, 2),
        required=True,
        help='Flat dollar amount of tax on income up to the lower bound of this bracket.',
    )
    marginal_rate = fields.Float(
        string='Marginal rate (%)',
        digits=(16, 4),
        required=True,
        help='Rate applied to income exceeding the lower bound (enter as whole percent, e.g. 5.20).',
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )

    @api.depends('tax_year', 'filing_status', 'income_from', 'income_to', 'marginal_rate')
    def _compute_name(self):
        labels = dict(self._fields['filing_status'].selection)
        for rec in self:
            rec.name = '%s / %s / $%s–$%s @ %s%%' % (
                rec.tax_year,
                labels.get(rec.filing_status, ''),
                '{:,.0f}'.format(rec.income_from),
                '{:,.0f}'.format(rec.income_to) if rec.income_to < 999_999_999 else '∞',
                rec.marginal_rate,
            )

    @api.constrains('income_from', 'income_to')
    def _check_range(self):
        for rec in self:
            if rec.income_to < rec.income_from:
                raise ValidationError(
                    'Upper bound must be >= lower bound on bracket %s.' % rec.display_name
                )

    @api.model
    def compute_annual_tax(self, tax_year, filing_status, annual_taxable, company=None):
        """Walk brackets and return total annual KS income tax."""
        company = company or self.env.company
        domain = [
            ('tax_year', '=', tax_year),
            ('filing_status', '=', filing_status),
            ('income_from', '<=', annual_taxable),
        ]
        brackets = self.search(
            domain + [('company_id', '=', company.id)],
            order='income_from asc',
        )
        if not brackets:
            brackets = self.search(
                domain + [('company_id', '=', False)],
                order='income_from asc',
            )
        if not brackets:
            return 0.0

        last = brackets[-1]
        excess = annual_taxable - last.income_from
        return last.base_tax + excess * (last.marginal_rate / 100.0)


class L10nKsTaxYearParams(models.Model):
    """Per-year exemption values published in the K-4 instructions / KW-100.

    Kansas uses a **tiered** personal-exemption system (SB 1, eff. 2024):

    * Single/HoH claiming >=1 allowance  → ``personal_exemption_single``
    * Married claiming exactly 1          → same value (``personal_exemption_single``)
    * Married claiming >=2                → ``personal_exemption_married``
    * Each *additional* dependent beyond the personal exemption(s) →
      ``dependent_exemption``
    """

    _name = 'l10n.ks.tax.year.params'
    _description = 'Kansas Payroll Tax Year Parameters'
    _order = 'tax_year desc'

    tax_year = fields.Integer(required=True, index=True)

    personal_exemption_single = fields.Float(
        string='Personal exemption — Single / HoH ($)',
        digits=(16, 2),
        help='Annual personal allowance for Single or Head of Household filers '
             'claiming at least 1 exemption (also used for Married claiming exactly 1).',
    )
    personal_exemption_married = fields.Float(
        string='Personal exemption — Married 2+ ($)',
        digits=(16, 2),
        help='Annual personal allowance for Married filers claiming 2 or more exemptions.',
    )
    dependent_exemption = fields.Float(
        string='Per-dependent exemption ($)',
        digits=(16, 2),
        help='Annual deduction per additional dependent beyond the personal exemption(s).',
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    notes = fields.Text()

    _sql_constraints = [
        ('l10n_ks_year_co_uniq', 'unique(tax_year, company_id)',
         'Only one parameter record per tax year per company.'),
    ]

    @api.model
    def get_params(self, tax_year, company=None):
        """Return the params record (or empty recordset) for a tax year."""
        company = company or self.env.company
        rec = self.search(
            [('tax_year', '=', tax_year), ('company_id', '=', company.id)],
            limit=1,
        )
        return rec

    def compute_total_exemption(self, filing_status, total_allowances):
        """Return total annual exemption amount given K-4 inputs.

        ``filing_status`` is ``'single'`` or ``'married'`` (mapped from the
        employee field before calling).
        ``total_allowances`` is the integer from K-4 Line 1 / Line 2.
        """
        self.ensure_one()
        if total_allowances <= 0:
            return 0.0

        if filing_status == 'married':
            if total_allowances == 1:
                personal = self.personal_exemption_single
                additional_count = 0
            else:
                personal = self.personal_exemption_married
                additional_count = max(0, total_allowances - 2)
        else:
            personal = self.personal_exemption_single
            additional_count = max(0, total_allowances - 1)

        return personal + additional_count * self.dependent_exemption
