{
    'name': 'LinkedERP Project Modifier',
    'version': '1.1.1',
    'summary': 'Adjustment for project and task views, also will related with time sheet',
    'description': """
LinkedERP Project Modifier
==========================

View and billing adjustments for projects and tasks:

* Task timesheets become read-only once the task or project sale order is completed.
* Task Sales Order Item scoped to the project sale order's own lines.
* Project followers shown on the project form as avatar tags.
""",
    'category': 'Project',
    'author': 'Muhammad Bintang',
    'website': 'https://linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'project', 'sale_project', 'hr_timesheet',
    ],
    'data': [
        'views/project_views_modifier.xml',
        'views/project_task_views_modifier.xml'
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
