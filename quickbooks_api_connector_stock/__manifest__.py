{
    'name': 'QuickBooks API Connector — Stock Bridge',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'QuickBooks Inventory Adjustment sync for Odoo stock',
    'description': """
        Bridge module that wires QuickBooks Online Inventory Adjustment
        sync into Odoo's Inventory module. Hooks ``stock.move._action_done``
        to enqueue adjustment pushes when a move is validated.
        Auto-installed when both ``quickbooks_api_connector`` and ``stock``
        are installed; safely absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'stock'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'application': False,
}
