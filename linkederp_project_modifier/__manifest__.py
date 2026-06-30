{
    'name': 'LinkedERP Project Modifier',
    'version': '1.0.1',
    'summary': 'Adjustment for project and task views, also will related with time sheet',
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
