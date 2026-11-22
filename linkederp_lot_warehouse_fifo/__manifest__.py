{
    'name': 'Batch Cost per Warehouse (FIFO)',
    'version': '19.0.1.0.0',
    'summary': 'FIFO cost kept per batch AND per warehouse',
    'description': """
For products valued by lot (FIFO), Odoo keeps one cost queue per batch for the whole company.
This module keeps it per batch per warehouse: a sale from a warehouse takes the cost of that
batch as it came into THAT warehouse. Transfers between warehouses carry the cost across.
Switch it on per product category ("Batch cost per warehouse").
Built and tested for Peerless Biotech on LinkedERP staging.
""",
    'author': 'LinkedERP',
    'license': 'LGPL-3',
    'depends': ['stock_account'],
    'data': ['views/product_category_views.xml'],
    'installable': True,
}
