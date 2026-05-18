{
    'name': 'QuickBooks API Connector — HR Payroll Bridge',
    'version': '19.0.2.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Payroll sync fields and archive for Odoo Payroll',
    'description': """
        Bridge module that wires QuickBooks Payroll GraphQL data into Odoo
        Payroll native models (hr.contract, hr.payslip, hr.payslip.input,
        hr.salary.rule, hr.payroll.structure, hr.payroll.structure.type)
        and into a dedicated read-only archive (qb.payroll.check) so that
        historical QuickBooks paychecks remain auditable after Odoo takes
        over as the live payroll system of record.

        Auto-installs when both ``hr_payroll`` and ``hr_contract`` are
        present in the addons path. Odoo's dependency resolver guarantees
        the module is silently skipped otherwise — the manifest no longer
        needs to be edited by hand.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'hr_payroll', 'hr_contract'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'post_init_hook': '_post_init_seed_payroll',
    'installable': True,
    'auto_install': True,
    'application': False,
}
