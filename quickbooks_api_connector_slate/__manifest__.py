{
    'name': 'QuickBooks API Connector — SLATE Bridge',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'SLATE integration registry hooks for QuickBooks',
    'description': """
        Bridge module that wires QuickBooks Online into the SLATE
        integration framework (``task.sync.manager`` and
        ``slate.integration.registry``). Auto-installed when both
        ``quickbooks_api_connector`` and ``slate_connector_v19`` are
        installed; safely absent otherwise.
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': ['quickbooks_api_connector', 'slate_connector_v19'],
    'data': [],
    'installable': True,
    'auto_install': True,
    'application': False,
}
