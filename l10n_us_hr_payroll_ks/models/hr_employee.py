"""
Kansas K-4 fields on hr.employee and the percentage-method withholding
computation called by the KS_SIT salary rule.

Formula source: NFC Bulletin NFC-24-1722617728 / Kansas KW-100 (eff. PP15 2024).
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_PERIODS_PER_YEAR = {
    'annually': 1,
    'semi-annually': 2,
    'semi_annually': 2,
    'quarterly': 4,
    'monthly': 12,
    'semi-monthly': 24,
    'semi_monthly': 24,
    'bi-weekly': 26,
    'bi_weekly': 26,
    'biweekly': 26,
    'bi-monthly': 6,
    'bi_monthly': 6,
    'bimonthly': 6,
    'weekly': 52,
    'daily': 260,
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
    @staticmethod
    def _l10n_ks_get_version(payslip):
        """Return the contract/version record from a payslip (Odoo 19 compat)."""
        for attr in ('version_id', 'contract_id'):
            rec = getattr(payslip, attr, None)
            if rec:
                return rec
        return None

    def _l10n_ks_pay_periods(self, version, payslip=None):
        """Return pay periods per year.

        Priority:
        1. version/contract ``schedule_pay`` field (if present and recognised).
        2. Derive from payslip date range length.
        3. Default 26 (bi-weekly) — the most common US payroll cycle.
        """
        self.ensure_one()
        if version:
            sched = getattr(version, 'schedule_pay', None)
            if sched:
                periods = _PERIODS_PER_YEAR.get(sched)
                if periods:
                    _logger.debug('KS_SIT: schedule_pay=%r → %s periods', sched, periods)
                    return periods
                _logger.warning(
                    'KS_SIT: unrecognised schedule_pay=%r on version %s',
                    sched, version.id)

        if payslip and payslip.date_from and payslip.date_to:
            d_from = payslip.date_from
            d_to = payslip.date_to
            if isinstance(d_from, str):
                d_from = fields.Date.from_string(d_from)
            if isinstance(d_to, str):
                d_to = fields.Date.from_string(d_to)
            span = (d_to - d_from).days + 1
            if span <= 7:
                p = 52
            elif span <= 16:
                p = 26
            elif span <= 20:
                p = 24
            elif span <= 35:
                p = 12
            elif span <= 95:
                p = 4
            else:
                p = 1
            _logger.debug('KS_SIT: derived %s periods from %s-day pay span', p, span)
            return p

        _logger.warning('KS_SIT: no schedule_pay and no payslip dates — defaulting to 26')
        return 26

    def _l10n_ks_period_gross(self, payslip, categories):
        """Current-period gross wages subject to KS withholding.

        ``categories`` is a BrowsableObject — use attribute access, not dict.
        Prefers the GROSS category total already computed by upstream salary
        rules. Falls back to the version/contract wage (assumed per-period).
        """
        self.ensure_one()
        try:
            gross = categories.GROSS
            if gross:
                _logger.debug('KS_SIT: got GROSS from categories = %.2f', float(gross))
                return float(gross)
            _logger.debug('KS_SIT: categories.GROSS returned falsy value: %r', gross)
        except (AttributeError, KeyError) as exc:
            _logger.debug('KS_SIT: categories.GROSS access failed: %s', exc)
        version = self._l10n_ks_get_version(payslip)
        if not version:
            _logger.debug('KS_SIT: no version/contract on payslip — gross = 0')
            return 0.0
        wage = float(version.wage or 0.0)
        _logger.debug('KS_SIT: falling back to version.wage = %.2f', wage)
        return wage

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
          3. Walk progressive brackets -> annual tax.
          4. De-annualize -> per-period tax.
          5. Add flat extra withholding.
        """
        self.ensure_one()

        emp = self.sudo()

        state = emp.address_id.state_id if emp.address_id else False
        if not state or state.code != 'KS':
            _logger.info('KS_SIT: employee %s — work state is %s, not KS. Skipping.',
                         emp.id, state.code if state else 'unset')
            return 0.0
        if emp.l10n_ks_exempt or emp.l10n_ks_filing_status == 'exempt':
            _logger.info('KS_SIT: employee %s — exempt. Skipping.', emp.id)
            return 0.0
        if not emp.l10n_ks_filing_status:
            _logger.info('KS_SIT: employee %s — no filing status set. Skipping.', emp.id)
            return 0.0

        version = self._l10n_ks_get_version(payslip)
        periods = self._l10n_ks_pay_periods(version, payslip=payslip)

        period_gross = self._l10n_ks_period_gross(payslip, categories)
        alloc_pct = emp.l10n_ks_nonresident_allocation_pct
        if alloc_pct and 0 < alloc_pct < 100.0:
            period_gross *= (alloc_pct / 100.0)

        annual_gross = period_gross * periods

        pay_date = payslip.date_to or payslip.date_from or fields.Date.context_today(emp)
        if isinstance(pay_date, str):
            pay_date = fields.Date.from_string(pay_date)
        tax_year = pay_date.year

        Params = self.env['l10n.ks.tax.year.params'].sudo()
        params = Params.get_params(tax_year, company=payslip.company_id)
        if not params:
            params = Params.get_params(tax_year - 1, company=payslip.company_id)
        total_exemption = 0.0
        if params:
            filing = emp._l10n_ks_map_filing()
            total_exemption = params.compute_total_exemption(
                filing, emp.l10n_ks_total_allowances or 0
            )
        else:
            _logger.warning('KS_SIT: no tax year params found for year %s or %s.',
                            tax_year, tax_year - 1)

        annual_taxable = max(0.0, annual_gross - total_exemption)

        Bracket = self.env['l10n.ks.withholding.bracket'].sudo()
        annual_tax = Bracket.compute_annual_tax(
            tax_year,
            emp._l10n_ks_map_filing(),
            annual_taxable,
            company=payslip.company_id,
        )

        per_period = annual_tax / periods if periods else 0.0

        extra = float(emp.l10n_ks_additional_withholding or 0.0)
        total = per_period + extra

        _logger.info(
            'KS_SIT: emp=%s filing=%s allowances=%s gross/period=%.2f '
            'periods=%s annual_gross=%.2f exemption=%.2f annual_taxable=%.2f '
            'annual_tax=%.2f per_period=%.2f extra=%.2f total=%.2f',
            emp.id, emp.l10n_ks_filing_status, emp.l10n_ks_total_allowances,
            period_gross, periods, annual_gross, total_exemption,
            annual_taxable, annual_tax, per_period, extra, total,
        )

        return -round(total, 2)
