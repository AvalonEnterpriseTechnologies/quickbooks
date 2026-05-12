{
    'name': 'QuickBooks API Connector — Sale Bridge',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Estimate sync for Odoo sale.order',
    'description': """
        Bridge module that wires QuickBooks Online Estimate sync into
        Odoo's Sales module. Auto-installed when both
        ``quickbooks_api_connector`` and ``sale`` are installed; safely
        absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'sale'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'application': False,
}
