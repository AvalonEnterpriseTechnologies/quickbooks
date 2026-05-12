{
    'name': 'QuickBooks API Connector — Purchase Bridge',
    'version': '19.0.1.0.1',
    'category': 'Accounting',
    'summary': 'QuickBooks Purchase Order sync for Odoo purchase',
    'description': """
        Bridge module that wires QuickBooks Online Purchase Order sync
        into Odoo's Purchase module. Auto-installed when both
        ``quickbooks_api_connector`` and ``purchase`` are installed;
        safely absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'purchase'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'application': False,
}
