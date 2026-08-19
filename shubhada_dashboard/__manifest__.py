{
    'name': 'Shubhada Management Dashboard',
    'version': '19.0.1.0.0',
    'summary': 'Group management dashboard for Shubhada Polymers: plant and '
               'product-family profitability, copper exposure, shop-floor throughput.',
    'description': 'Branded management dashboard for the Shubhada Polymers demo. '
                   'Serves a self-contained live dashboard page (Chart.js from Odoo web '
                   'assets, data over call_kw as the logged-in user) with drill-down '
                   'act_window records for every figure. Same pattern as '
                   'alsafa_control_tower.',
    'category': 'Productivity/Dashboard',
    'author': 'LinkedERP',
    'license': 'LGPL-3',
    'depends': ['web', 'sale_management', 'purchase', 'stock', 'mrp', 'quality_control', 'account'],
    'data': [
        'views/actions.xml',
        'views/menu.xml',
    ],
    'application': True,
    'installable': True,
}
