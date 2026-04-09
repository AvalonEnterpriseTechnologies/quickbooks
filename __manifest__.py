{
    'name': 'QuickBooks API Module',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Independent QuickBooks Online connector for Odoo 19',
    'description': """
        Standalone QuickBooks Online integration module for Odoo 19.

        Features:
        - OAuth 2.0 connection to QuickBooks Online
        - Bidirectional sync: customers, vendors, products, invoices,
          bills, payments, journal entries, tax codes
        - Async queue-based processing with retry and backoff
        - Conflict resolution (last modified, Odoo wins, QBO wins, manual)
        - Configurable field mappings
        - Webhook support (CloudEvents + legacy format)
        - Rate-limited API client (sliding window, 450 req/min)

        Optionally integrates with slate_connector_v19 if installed
        (integration registry, event bus, cross-entity mapping).
    """,
    'author': 'Avalon Enterprise Technologies',
    'website': 'https://github.com/AvalonEnterpriseTechnologies/quickbooks_odoo_module',
    'license': 'LGPL-3',
    'depends': [
        'base', 'mail', 'account', 'product', 'contacts',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        # Security groups (must come before access CSV)
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        # Data
        'data/cron_jobs.xml',
        'data/mail_templates.xml',
        'data/default_field_mappings.xml',
        # Views
        'views/quickbooks_config_views.xml',
        'views/quickbooks_sync_log_views.xml',
        'views/quickbooks_sync_queue_views.xml',
        'views/wizard_views.xml',
        'views/menu_items.xml',
        'views/res_partner_views.xml',
        'views/product_views.xml',
        'views/account_move_views.xml',
        'views/oauth_result_template.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': True,
}
