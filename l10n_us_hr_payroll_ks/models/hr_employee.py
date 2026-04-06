# -*- coding: utf-8 -*-
"""
Kansas K-4 fields on hr.employee and the percentage-method withholding
computation called by the KS_SIT salary rule.

Formula source: NFC Bulletin NFC-24-1722617728 / Kansas KW-100 (eff. PP15 2024).
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_PERIODS_PER_YEAR = {
    'annually': 1,
    'semi-annually': 2,
    'quarterly': 4,
    'monthly': 12,
    'semi-monthly': 24,
    'bi-weekly': 26,
    'bi_monthly': 6,
    'weekly': 52,
}


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ------------------------------------------------------------------
    # K-4 fields
    # ------------------------------------------------------------------
    l10n_ks_filing_status = fields.Selection(
        [
            ('single', 'Kansas: Single / Head of Household'),
            ('married', 'Kansas: Married'),
            ('exempt', 'Kansas: Exempt from withholding'),
        ],
        string='Kansas K-4 filing status',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_ks_total_allowances = fields.Integer(
        string='Kansas total allowances (K-4)',
        default=0,
        groups='hr_payroll.group_hr_payroll_user',
        help='Total number of withholding allowances from K-4. '
             'First 1 (single) or 2 (married) allowances apply the personal '
             'exemption; additional ones apply the dependent exemption.',
    )
    l10n_ks_additional_withholding = fields.Monetary(
        string='Kansas extra withholding (per pay period)',
        currency_field='currency_id',
        groups='hr_payroll.group_hr_payroll_user',
        help='Additional flat dollar amount to withhold each pay period '
             '(K-4 Line 6 equivalent).',
    )
    l10n_ks_nonresident_allocation_pct = fields.Float(
        string='Nonresident allocation %',
        digits=(16, 4),
        groups='hr_payroll.group_hr_payroll_user',
        help='K-4C: percentage of wages allocated to Kansas. '
             'Leave at 0 or 100 for full-time Kansas residents.',
    )
    l10n_ks_exempt = fields.Boolean(
        string='Kansas exempt (no SIT)',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_ks_form_effective_date = fields.Date(
        string='K-4 effective date',
        groups='hr_payroll.group_hr_payroll_user',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )
    l10n_ks_is_kansas_work_state = fields.Boolean(
        compute='_compute_l10n_ks_is_kansas_work_state',
    )

    # ------------------------------------------------------------------
    # Compute / constraints
    # ------------------------------------------------------------------
    @api.depends('address_id', 'address_id.state_id')
    def _compute_l10n_ks_is_kansas_work_state(self):
        for emp in self:
            state = emp.address_id.state_id if emp.address_id else False
            emp.l10n_ks_is_kansas_work_state = state.code == 'KS' if state else False

    @api.constrains('l10n_ks_filing_status', 'l10n_ks_exempt', 'l10n_ks_total_allowances')
    def _check_l10n_ks_exempt_consistency(self):
        for emp in self:
            if (emp.l10n_ks_filing_status == 'exempt' or emp.l10n_ks_exempt) \
                    and emp.l10n_ks_total_allowances:
                raise ValidationError(
                    'Kansas-exempt employees should not claim withholding allowances.'
                )

    # ------------------------------------------------------------------
    # Helpers for the salary rule
    # ------------------------------------------------------------------
    def _l10n_ks_pay_periods(self, contract):
        """Return pay periods per year from the contract schedule."""
        self.ensure_one()
        if contract and contract.schedule_pay:
            return _PERIODS_PER_YEAR.get(contract.schedule_pay, 12)
        return 12

    def _l10n_ks_period_gross(self, payslip, categories):
        """Current-period gross wages subject to KS withholding.

        Prefers the ``GROSS`` rule-category total already computed by upstream
        salary rules.  Falls back to the contract wage (assumed per-period).
        """
        self.ensure_one()
        gross = categories.get('GROSS')
        if gross is not None and gross != 0:
            return float(gross)
        contract = payslip.contract_id
        if not contract:
            return 0.0
        return float(contract.wage or 0.0)

    def _l10n_ks_map_filing(self):
        """Map the employee selection to the bracket filing_status key."""
        self.ensure_one()
        if self.l10n_ks_filing_status == 'married':
            return 'married'
        return 'single'

    # ------------------------------------------------------------------
    # Main computation — called from KS_SIT salary rule
    # ------------------------------------------------------------------
    def _l10n_ks_compute_sit_line(self, payslip, categories):
        """Return the payslip line amount (negative = employee deduction).

        Implements the NFC / KW-100 percentage method:
          1. Annualize period gross.
          2. Subtract personal + dependent exemptions.
          3. Walk progressive brackets → annual tax.
          4. De-annualize → per-period tax.
          5. Add flat extra withholding.
        """
        self.ensure_one()

        # Gate: must be a Kansas work-state employee with a valid filing status
        state = self.address_id.state_id if self.address_id else False
        if not state or state.code != 'KS':
            return 0.0
        if self.l10n_ks_exempt or self.l10n_ks_filing_status == 'exempt':
            return 0.0
        if not self.l10n_ks_filing_status:
            return 0.0

        contract = payslip.contract_id
        periods = self._l10n_ks_pay_periods(contract)

        # --- 1. Annualize ---------------------------------------------------
        period_gross = self._l10n_ks_period_gross(payslip, categories)
        alloc_pct = self.l10n_ks_nonresident_allocation_pct
        if alloc_pct and 0 < alloc_pct < 100.0:
            period_gross *= (alloc_pct / 100.0)

        annual_gross = period_gross * periods

        # --- 2. Exemptions ---------------------------------------------------
        pay_date = payslip.date_to or payslip.date_from or fields.Date.context_today(self)
        if isinstance(pay_date, str):
            pay_date = fields.Date.from_string(pay_date)
        tax_year = pay_date.year

        Params = self.env['l10n.ks.tax.year.params']
        params = Params.get_params(tax_year, company=payslip.company_id)
        if not params:
            params = Params.get_params(tax_year - 1, company=payslip.company_id)
        total_exemption = 0.0
        if params:
            filing = self._l10n_ks_map_filing()
            total_exemption = params.compute_total_exemption(
                filing, self.l10n_ks_total_allowances or 0
            )

        annual_taxable = max(0.0, annual_gross - total_exemption)

        # --- 3. Brackets → annual tax ----------------------------------------
        Bracket = self.env['l10n.ks.withholding.bracket']
        annual_tax = Bracket.compute_annual_tax(
            tax_year,
            self._l10n_ks_map_filing(),
            annual_taxable,
            company=payslip.company_id,
        )

        # --- 4. De-annualize -------------------------------------------------
        per_period = annual_tax / periods if periods else 0.0

        # --- 5. Extra withholding --------------------------------------------
        extra = float(self.l10n_ks_additional_withholding or 0.0)
        total = per_period + extra

        return -round(total, 2) if total else 0.0
