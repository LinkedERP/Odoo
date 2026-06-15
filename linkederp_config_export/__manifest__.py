# -*- coding: utf-8 -*-
{
    'name': 'Configuration Export',
    'version': '1.0.0',
    'category': 'Technical',
    'summary': 'Export Odoo configuration settings to Excel – grouped per installed module',
    'description': (
        "Export configured values from your Odoo database to a professional Excel workbook, "
        "grouped by functional area. "
        "Areas are auto-selected based on installed modules — no manual setup needed. "
        "Reads real values from res.config.settings, res.company, account.account, "
        "stock.warehouse, etc. "
        "Only depends on base + mail; all other modules detected at runtime. "
        "Requires: pip install openpyxl"
    ),
    'author': 'Muhammad Bintang',
    'website': '',
    'depends': [
        # ── Core only – all other modules are auto-detected at runtime ─────────
        'base',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/config_area_data.xml',
        'views/config_export_views.xml',
    ],
    'external_dependencies': {
        'python': ['openpyxl'],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
