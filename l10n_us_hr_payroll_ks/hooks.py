"""
Post-install hook: create the KS_SIT salary rule and attach it to the first
U.S. payroll structure found.  We do this in Python (not XML) because Odoo 19
Enterprise enforces NOT NULL on hr.salary.rule.struct_id and the US structure
XML ID varies across builds.
"""

import logging

_logger = logging.getLogger(__name__)

RULE_XMLID = 'l10n_us_hr_payroll_ks.hr_salary_rule_ks_sit'
CAT_XMLID = 'l10n_us_hr_payroll_ks.hr_salary_rule_category_ks_sit'

RULE_CODE = 'KS_SIT'
RULE_PYTHON = 'result = employee._l10n_ks_compute_sit_line(payslip, categories)\n'


def _find_us_structure(env):
    """Return the first US payroll structure, trying several lookup strategies."""
    Structure = env['hr.payroll.structure']

    for xmlid in (
        'l10n_us_hr_payroll.hr_payroll_structure_us_employee',
        'l10n_us_hr_payroll.hr_payroll_structure_usa_employee',
        'l10n_us_hr_payroll.hr_payroll_structure_us_regular_pay',
        'l10n_us_hr_payroll.hr_payroll_structure_us',
    ):
        try:
            struct = env.ref(xmlid, raise_if_not_found=False)
            if struct:
                return struct
        except Exception:
            pass

    struct = Structure.search([('country_id.code', '=', 'US')], limit=1)
    if struct:
        return struct

    struct = Structure.search([('name', 'ilike', 'united states')], limit=1)
    return struct


def post_init_hook(env):
    """Odoo 17+ hook signature: receives ``env`` directly."""

    us_struct = _find_us_structure(env)
    if not us_struct:
        _logger.warning(
            'l10n_us_hr_payroll_ks: no US payroll structure found — '
            'KS_SIT rule NOT created.  Add it manually after install.'
        )
        return

    category = env.ref(CAT_XMLID, raise_if_not_found=False)
    if not category:
        _logger.warning(
            'l10n_us_hr_payroll_ks: KS_SIT category not found — aborting rule creation.'
        )
        return

    existing = env['hr.salary.rule'].search([('code', '=', RULE_CODE)], limit=1)
    if existing:
        _logger.info('l10n_us_hr_payroll_ks: KS_SIT rule already exists (id=%s).', existing.id)
        return

    rule_vals = {
        'name': 'Kansas State Income Tax',
        'code': RULE_CODE,
        'sequence': 350,
        'category_id': category.id,
        'struct_id': us_struct.id,
        'condition_select': 'none',
        'amount_select': 'code',
        'amount_python_compute': RULE_PYTHON,
        'appears_on_payslip': True,
    }

    rule = env['hr.salary.rule'].create(rule_vals)

    env['ir.model.data'].create({
        'module': 'l10n_us_hr_payroll_ks',
        'name': 'hr_salary_rule_ks_sit',
        'model': 'hr.salary.rule',
        'res_id': rule.id,
        'noupdate': True,
    })

    _logger.info(
        'l10n_us_hr_payroll_ks: created KS_SIT rule (id=%s) on structure %s (id=%s).',
        rule.id, us_struct.name, us_struct.id,
    )
