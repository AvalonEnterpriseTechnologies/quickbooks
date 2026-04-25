{
    'name': 'Project Open Tasks by Person Report',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Project reporting dashboard for open and late tasks by person',
    'description': """
        Adds a Project reporting menu entry that summarizes:
        - Active projects opened by each person
        - Open project tasks assigned to each person
        - Late open tasks based on the built-in task deadline
    """,
    'author': 'Miltech',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['project'],
    'data': [
        'security/ir.model.access.csv',
        'reports/project_task_person_report_templates.xml',
        'views/project_task_person_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
