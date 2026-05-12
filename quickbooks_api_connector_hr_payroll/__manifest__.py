{
    'name': 'QuickBooks API Connector — HR Payroll Bridge',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Payroll sync fields for Odoo Payroll',
    'description': """
        Bridge module that wires QuickBooks Payroll GraphQL data into Odoo
        Payroll native models. Auto-installed when both
        ``quickbooks_api_connector`` and ``hr_payroll`` are installed.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'hr_payroll'],
    'data': [
        'views/hr_payroll_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
