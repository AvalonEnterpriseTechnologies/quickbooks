# -*- coding: utf-8 -*-
{
    'name': 'United States - Payroll: Kansas Withholding (K-4)',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Kansas state income tax withholding from K-4 inputs and configurable KW-100-style tables',
    'description': """
Kansas payroll withholding extension
====================================

Adds Kansas (K-4) filing status and allowance fields on employees, maintenance
screens for effective-dated withholding tables, and a salary rule that computes
KS SIT from annualized gross pay.

**Important:** Load official Kansas Department of Revenue withholding tables for
each tax year (KW-100). The module ships illustrative placeholder lines only;
replace them before relying on amounts for live payroll.

After install, the Kansas salary rule is attached automatically to payroll
structures linked to the United States. If your database uses custom structures,
add rule **KS_SIT** to those structures manually.
    """,
    'author': 'Miltech Manufacturing',
    'license': 'LGPL-3',
    'depends': [
        'hr_payroll',
        'hr_contract',
        'l10n_us_hr_payroll',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/hr_salary_rule_data.xml',
        'data/ks_withholding_table_data.xml',
        'views/ks_withholding_table_views.xml',
        'views/hr_employee_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
