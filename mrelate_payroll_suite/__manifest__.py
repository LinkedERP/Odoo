# -*- coding: utf-8 -*-
{
    "name": "India Payroll Suite (Dashboards, Reports, One-Click Monthly Run)",
    "version": "19.0.1.3.0",
    "category": "Human Resources/Payroll",
    "summary": "Adds dashboards, Form 12BB declaration printout and a "
               "one-click Monthly Payroll Run wizard on top of the India "
               "TDS module. Built for SMEs (20-50 employees) - minimal HR "
               "intervention.",
    "description": """
India Payroll Suite
===================
Wraps ``mrelate_payroll_tds`` and ``mrelate_payroll_expense_integration`` with:

* Graph + pivot views on TDS declarations (by regime, FY, recommended-vs-applied)
* Graph + pivot views on payslips (gross/net/TDS by month/department)
* TDS Register report (group-by FY + regime + employee)
* Form 12BB-style declaration printout (PDF via QWeb)
* "Monthly Payroll Run" wizard - for each active India employee in the
  selected company:
    1. Verifies/creates the TDS declaration for the current FY
    2. Refreshes the salary projection from existing payslips
    3. Re-applies the latest approved declaration to the contract version
    4. Creates a draft payslip for the period (if missing) with
       worked-days auto-filled from the resource calendar
    5. Refreshes approved/reimbursable expenses onto the draft
    6. Presents a summary; HR reviews + validates

Safety: never validates a payslip, never creates accounting entries.
Designed to be installed by Indian SMEs and resold as a service.
""",
    "author": "Mrelate / LinkedERP",
    "website": "https://www.linkederp.com",
    "license": "LGPL-3",
    "depends": [
        "mrelate_payroll_tds",
        "mrelate_payroll_expense_integration",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/payroll_run_wizard_views.xml",
        "views/tds_dashboard_views.xml",
        "views/payslip_dashboard_views.xml",
        "views/menus.xml",
        "reports/form_12bb_template.xml",
        "reports/form_12bb_report.xml",
        "reports/payslip_template.xml",
        "reports/payslip_report.xml",
        "views/hr_payslip_views.xml",
        "views/tds_declaration_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
