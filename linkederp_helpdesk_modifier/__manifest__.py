{
    'name': 'LinkedERP Helpdesk Modifier',
    'version': '1.0.1',
    'summary': 'Auto email reminder for unanswered helpdesk tickets after 3 days',
    'category': 'Helpdesk',
    'author': 'LinkedERP',
    'website': 'https://linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'helpdesk',
        'mail',
    ],
    'data': [
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/helpdesk_team_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
