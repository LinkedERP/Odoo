{
    'name': 'LinkedERP Sales Modifier',
    'version': '1.0.5',
    'summary': 'Hide locked Sales Orders from default views and timesheet SO selection',
    'description': """
LinkedERP Sales Modifier
========================

Keeps completed sale orders out of day-to-day views and simplifies locking:

* Open Orders / Complete Order filters on Sales Order and Quotation search views.
* Sales Orders and Quotations default to showing open orders (clearable by users).
* action_lock / action_unlock lock or unlock regardless of invoice status.
""",
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
