# -*- coding: utf-8 -*-
"""Attach KS salary rule to U.S. payroll structures (IDs differ by Odoo version)."""

from odoo import SUPERUSER_ID, api


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        rule = env.ref('l10n_us_hr_payroll_ks.hr_salary_rule_ks_sit')
    except ValueError:
        return

    Structure = env['hr.payroll.structure']
    us_structures = Structure.search([('country_id.code', '=', 'US')])
    if not us_structures:
        us_structures = Structure.search([('name', 'ilike', 'united states')])
    if not us_structures:
        return

    Rule = env['hr.salary.rule']
    rule_fields = Rule._fields

    if 'struct_ids' in rule_fields:
        merged = rule.struct_ids | us_structures
        rule.struct_ids = [(6, 0, merged.ids)]
    elif 'struct_id' in rule_fields:
        if not rule.struct_id:
            rule.struct_id = us_structures[0].id
    elif 'rule_ids' in Structure._fields:
        field = Structure._fields['rule_ids']
        if field.comodel_name == 'hr.salary.rule':
            for struct in us_structures:
                if rule not in struct.rule_ids:
                    struct.write({'rule_ids': [(4, rule.id)]})
