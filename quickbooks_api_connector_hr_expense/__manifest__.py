{
    'name': 'QuickBooks API Connector — HR Expense Bridge',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Purchase sync for Odoo hr.expense',
    'description': """
        Bridge module that wires QuickBooks Online Purchase sync into
        Odoo's HR Expenses module. Auto-installed when both
        ``quickbooks_api_connector`` and ``hr_expense`` are installed;
        safely absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'hr_expense'],
    'data': [
        'views/hr_expense_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
