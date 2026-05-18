{
    'name': 'QuickBooks API Connector — HR Bridge',
    'version': '19.0.2.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Employee and Department sync for Odoo HR',
    'description': """
        Bridge module that wires QuickBooks Online employee, department,
        work-location, pay-schedule, and workers-comp data onto Odoo's
        HR module. Auto-installed when both ``quickbooks_api_connector``
        and ``hr`` are installed; safely absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'hr'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/qb_dedupe_employees_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
