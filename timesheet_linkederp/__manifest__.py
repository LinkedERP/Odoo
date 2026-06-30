{
    'name': 'Timesheet Cross Company Blocker',
    'version': '1.0.2',
    'summary': 'Project and User company should be same while filling Timesheet',
    'category': 'Accounting',
    'author': 'JV',
    'website': 'https://Linkederp.com',
    'license': 'AGPL-3',
    'depends': ['account', 'hr_timesheet', 'sale_timesheet','helpdesk_sale_timesheet'],
    'data': [
    'views/timesheet_views.xml'
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
