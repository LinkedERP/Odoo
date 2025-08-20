# -*- coding: utf-8 -*-
{
    'name': "POS Company Logo",
    'category': 'Point of Sale',
    'summary': """Customize the logo shown in the POS interface
		keywords: Customize POS logo | Change POS logo | POS branding | POS company logo | Odoo POS logo""",
    'description': """
            This module allows you to replace the default Odoo logo in the Point of Sale (POS) interface with your own company logo, improving branding and visual identity during POS operations.
    """,
    'author': "Dustin Mimbela",
    'version': '1.0',
    'installable': True,
    'depends': ['point_of_sale'],
    'data': [],
    'assets': {
        "point_of_sale.assets_prod": [
            "pos_company_logo/static/src/**/*",
        ],
    },
    'license': 'LGPL-3',
    'images': ['static/description/banner.png']
}
