{
    'name': 'Shop Schedule',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Visual shop floor scheduling board with Kanban work order tracking',
    'description': """
        Shop scheduling module for Miltech that provides:
        - CRM-style Kanban board for tracking work orders through machine stages
        - Drag-and-drop work orders between workstations (Lathe, Mill, QC, etc.)
        - Full work order detail with ProShop ERP field mapping
        - Operation routing steps per work order
        - Links back to CRM leads/opportunities
        - List, Calendar, and Search views with rich filtering
    """,
    'author': 'Miltech',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['crm', 'mail'],
    'data': [
        'security/shop_schedule_groups.xml',
        'security/ir.model.access.csv',
        'data/shop_schedule_data.xml',
        'views/shop_schedule_category_views.xml',
        'views/shop_schedule_stage_views.xml',
        'views/shop_schedule_tag_views.xml',
        'views/shop_schedule_order_views.xml',
        'views/shop_schedule_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
