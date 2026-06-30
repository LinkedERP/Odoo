# -*- coding: utf-8 -*-
{
    "name": "Mrelate Payroll Expense Integration",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "summary": "Refresh approved, reimbursable expenses into an existing draft "
               "payslip (closes the late-approval gap in hr_payroll_expense).",
    "description": """
Mrelate Payroll Expense Integration
===================================
Small, isolated extension of the standard ``hr_payroll_expense`` bridge.

Problem it solves
-----------------
Standard Odoo attaches approved, employee-paid expenses flagged "Reimburse in
Next Payslip" to a payslip only at *payslip creation time*. If a draft payslip
already exists and an expense is approved afterwards, clicking **Compute Sheet**
does NOT pull the expense in. HR/payroll were forced to link records by hand.

What this module adds
---------------------
* A **Refresh Expenses** button on draft payslips that searches eligible
  approved/own-account/reimbursable/unlinked expenses for the same employee and
  company and attaches them through the standard ``expense_ids`` relation, then
  recomputes.
* Draft-only auto-refresh inside ``compute_sheet`` so that clicking Compute also
  pulls late-approved expenses. Non-draft payslips are never touched.

Safety
------
* Only acts on payslips in state ``draft``.
* Never posts a payslip, never posts an expense, never creates a payment or
  journal entry.
* Never detaches expenses and never touches expenses already linked to another
  payslip (domain filters ``payslip_id = False``), so it is fully idempotent.
* Adds no new models and no new access rules.

See README.md and DEPLOY_AND_UAT.md for design notes, UAT and rollback.
""",
    "author": "Mrelate / LinkedERP",
    "website": "https://www.linkederp.com",
    "license": "LGPL-3",
    "depends": [
        "hr_payroll_expense",
    ],
    "data": [
        "views/hr_payslip_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
