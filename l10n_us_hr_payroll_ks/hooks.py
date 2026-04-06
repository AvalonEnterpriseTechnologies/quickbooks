"""
Post-install hook for l10n_us_hr_payroll_ks.

Creates the KS_SIT salary rule and configuration menu items dynamically
because several XML IDs (struct_id, parent menu) differ across Odoo 19 builds.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = 'l10n_us_hr_payroll_ks'
CAT_XMLID = f'{MODULE}.hr_salary_rule_category_ks_sit'
RULE_CODE = 'KS_SIT'
RULE_PYTHON = 'result = employee._l10n_ks_compute_sit_line(payslip, categories)\n'

_CONFIG_MENU_CANDIDATES = [
    'hr_payroll.menu_hr_payroll_configuration',
    'hr_payroll.payroll_menu_configuration',
    'hr_payroll.menu_payroll_configuration',
    'hr_payroll.hr_payroll_menu_configuration',
    'hr_payroll.menu_configuration',
]

_ROOT_MENU_CANDIDATES = [
    'hr_payroll.menu_hr_payroll_root',
    'hr_payroll.payroll_menu_root',
    'hr_payroll.menu_payroll_root',
]


def _resolve_first(env, xmlid_list):
    for xmlid in xmlid_list:
        try:
            rec = env.ref(xmlid, raise_if_not_found=False)
            if rec:
                return rec
        except Exception:
            pass
    return None


def _find_us_structure(env):
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
    return Structure.search([('name', 'ilike', 'united states')], limit=1)


def _register_xmlid(env, name, model, res_id):
    env['ir.model.data'].create({
        'module': MODULE,
        'name': name,
        'model': model,
        'res_id': res_id,
        'noupdate': True,
    })


def _create_salary_rule(env):
    us_struct = _find_us_structure(env)
    if not us_struct:
        _logger.warning('%s: no US payroll structure found — KS_SIT rule NOT created.', MODULE)
        return

    category = env.ref(CAT_XMLID, raise_if_not_found=False)
    if not category:
        _logger.warning('%s: KS_SIT category not found — aborting rule creation.', MODULE)
        return

    existing = env['hr.salary.rule'].search([('code', '=', RULE_CODE)], limit=1)
    if existing:
        _logger.info('%s: KS_SIT rule already exists (id=%s).', MODULE, existing.id)
        return

    rule = env['hr.salary.rule'].create({
        'name': 'Kansas State Income Tax',
        'code': RULE_CODE,
        'sequence': 350,
        'category_id': category.id,
        'struct_id': us_struct.id,
        'condition_select': 'none',
        'amount_select': 'code',
        'amount_python_compute': RULE_PYTHON,
        'appears_on_payslip': True,
    })
    _register_xmlid(env, 'hr_salary_rule_ks_sit', 'hr.salary.rule', rule.id)
    _logger.info(
        '%s: created KS_SIT rule (id=%s) on structure %s (id=%s).',
        MODULE, rule.id, us_struct.name, us_struct.id,
    )


def _create_menus(env):
    parent = _resolve_first(env, _CONFIG_MENU_CANDIDATES)
    if not parent:
        parent = _resolve_first(env, _ROOT_MENU_CANDIDATES)
    if not parent:
        Menu = env['ir.ui.menu']
        parent = Menu.search([('name', 'ilike', 'configuration')], limit=1)
    if not parent:
        _logger.warning('%s: no payroll config menu found — skipping menu creation.', MODULE)
        return

    manager_group = env.ref('hr_payroll.group_hr_payroll_manager', raise_if_not_found=False)
    group_ids = [(6, 0, [manager_group.id])] if manager_group else []

    bracket_action = env.ref(f'{MODULE}.action_l10n_ks_bracket', raise_if_not_found=False)
    params_action = env.ref(f'{MODULE}.action_l10n_ks_params', raise_if_not_found=False)

    Menu = env['ir.ui.menu']

    if bracket_action:
        existing = env['ir.model.data'].search([
            ('module', '=', MODULE), ('name', '=', 'menu_l10n_ks_bracket'),
        ], limit=1)
        if not existing:
            menu = Menu.create({
                'name': 'Kansas Withholding Brackets',
                'parent_id': parent.id,
                'action': f'ir.actions.act_window,{bracket_action.id}',
                'sequence': 92,
                'groups_id': group_ids,
            })
            _register_xmlid(env, 'menu_l10n_ks_bracket', 'ir.ui.menu', menu.id)

    if params_action:
        existing = env['ir.model.data'].search([
            ('module', '=', MODULE), ('name', '=', 'menu_l10n_ks_params'),
        ], limit=1)
        if not existing:
            menu = Menu.create({
                'name': 'Kansas Tax Year Parameters',
                'parent_id': parent.id,
                'action': f'ir.actions.act_window,{params_action.id}',
                'sequence': 93,
                'groups_id': group_ids,
            })
            _register_xmlid(env, 'menu_l10n_ks_params', 'ir.ui.menu', menu.id)


def post_init_hook(env):
    """Odoo 17+ hook signature: receives ``env`` directly."""
    _create_salary_rule(env)
    _create_menus(env)
