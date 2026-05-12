{
    'name': 'QuickBooks API Connector — Project Bridge',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Project sync for Odoo project',
    'description': """
        Bridge module that wires QuickBooks Online Project sync into
        Odoo's Project module. Auto-installed when both
        ``quickbooks_api_connector`` and ``project`` are installed;
        safely absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'project'],
    'data': [
        'views/project_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
