{
    "name": "LinkedERP Dashboard Studio",
    "summary": "Native dashboard builder and Sales/CRM dashboard pack for Odoo",
    "description": """
LinkedERP Dashboard Studio adds a modern dashboard workspace inside Odoo.

The first release includes configurable KPI, chart, and table widgets plus a
ready-to-use Sales/CRM dashboard pack. Dashboards are grouped into
permissioned buckets (Sales, Ops, Finance, HR, Management). Access is granted
per bucket via security groups; once a user may see a dashboard, its numbers
are computed with elevated rights so every viewer sees the same figures.
Drill-down record lists still respect the viewer's own access rights.
    """,
    "version": "19.0.1.8.1",
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
        "views/sale_order_sla_views.xml",
        "report/sla_report.xml",
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
