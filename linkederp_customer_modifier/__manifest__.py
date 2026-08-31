{
    'name': 'LinkedERP Customer Modifier',
    'version': '1.1.0',
    'summary': 'Add multiple email receivers for invoice payment follow-up reminders',
    'category': 'Accounting',
    'author': 'LinkedERP',
    'website': 'https://linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'account_followup',
    ],
    'data': [
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
