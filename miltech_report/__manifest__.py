{
    'name': 'Miltech CRM Report',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Live CRM dashboard and reporting for Miltech',
    'description': """
        Custom CRM reporting module for Miltech that provides:
        - Live dashboard with KPI cards (pipeline, quotes, POs)
        - Pipeline breakdown by stage, customer, and salesperson
        - Date range and multi-criteria filtering
        - XLSX export of dashboard data
        - Integration with Studio-created PO Number field
    """,
    'author': 'Miltech',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
        'views/miltech_report_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'miltech_report/static/src/css/miltech_dashboard.css',
            'miltech_report/static/src/js/miltech_dashboard.js',
            'miltech_report/static/src/xml/miltech_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
