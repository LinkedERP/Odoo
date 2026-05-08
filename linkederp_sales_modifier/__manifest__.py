{
    'name': 'LinkedERP Sales Modifier',
    'version': '1.0.4',
    'summary': 'Hide locked Sales Orders from default views and timesheet SO selection',
    'category': 'Sales',
    'author': 'LinkedERP',
    'website': 'https://linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'sale',
        'sale_timesheet',
    ],
    'data': [
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
