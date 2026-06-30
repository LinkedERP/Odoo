{
    "name": "LinkedERP Dashboard Studio",
    "summary": "Native dashboard builder and Sales/CRM dashboard pack for Odoo",
    "description": """
LinkedERP Dashboard Studio adds a modern dashboard workspace inside Odoo.

The first release includes configurable KPI, chart, and table widgets plus a
ready-to-use Sales/CRM dashboard pack. Dashboard data is read through normal
Odoo ORM calls, so user access rights, record rules, and multi-company rules
continue to apply.
    """,
    "version": "19.0.1.0.0",
    "category": "Productivity/Dashboards",
    "author": "LinkedERP",
    "website": "https://linkederp.com",
    "license": "LGPL-3",
    "depends": [
        "web",
        "sale_management",
        "crm",
        "hr_timesheet",
        "planning",
    ],
    "data": [
        "security/dashboard_security.xml",
        "security/ir.model.access.csv",
        "views/dashboard_views.xml",
        "views/dashboard_menus.xml",
        "data/sales_crm_dashboard.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "linkederp_dashboard_studio/static/src/dashboard/dashboard_action.js",
            "linkederp_dashboard_studio/static/src/dashboard/dashboard_action.xml",
            "linkederp_dashboard_studio/static/src/dashboard/dashboard_styles.scss",
        ],
    },
    "application": True,
    "installable": True,
}
