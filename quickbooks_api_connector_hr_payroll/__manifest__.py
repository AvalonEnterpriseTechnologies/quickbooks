{
    'name': 'QuickBooks API Connector — HR Payroll Bridge',
    'version': '19.0.1.0.2',
    'category': 'Accounting',
    'summary': 'QuickBooks Payroll sync fields for Odoo Payroll',
    'description': """
        Bridge module that wires QuickBooks Payroll GraphQL data into Odoo
        Payroll native models (hr.contract, hr.payslip, hr.payslip.input,
        hr.salary.rule, hr.payroll.structure.type).

        Requires the Enterprise HR Payroll stack (``hr_payroll`` and
        ``hr_contract``). It is shipped with ``installable=False`` so that
        Odoo installations that do not have those Enterprise modules in
        their addons path can still load the rest of the
        ``quickbooks_api_connector`` family. Flip ``installable`` to True
        in this manifest only after confirming that ``hr_payroll`` AND
        ``hr_contract`` are both present in the addons path; the module
        will then auto-install when both are installed.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'hr_payroll', 'hr_contract'],
    'data': [],
    'installable': False,
    'auto_install': True,
    'application': False,
}
