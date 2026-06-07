# -*- coding: utf-8 -*-
{
    "name": "India Payroll TDS & Income-Tax Declaration",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "summary": "Employee income-tax declaration, old/new regime engine and monthly TDS "
               "computation for Indian payroll (FY 2026-27). Marginal relief, "
               "sec 206AA, age-based exemption, regime lock, drift detection.",
    "description": """
Mrelate India Payroll TDS
=========================
Custom, isolated module that adds a proper Indian income-tax declaration and
monthly TDS calculation on top of the standard Odoo India Payroll localization.

It does NOT modify standard l10n_in_hr_payroll rules. It computes a monthly TDS
amount and (on approval) writes it to the existing ``hr.version.l10n_in_tds``
field, which the standard payslip rule already deducts.

Phase 1 (MVP):
  * Employee tax-regime selection (old / new)
  * Annual tax declaration (PAN, previous employer, other income, 80C/80D/80CCD,
    home-loan interest, HRA inputs)
  * Salary projection (paid YTD + current month + projected remaining + bonus)
  * Dual-regime tax engine (slabs, standard deduction, rebate, surcharge, cess)
  * Approval workflow + audit trail (mail.thread)
  * Old-vs-new comparison and a human-readable calculation breakdown
  * Configurable, data-driven tax rates (future years added as data, not code)

v1.2.0 additions:
  * Marginal relief at 87A rebate boundary (new regime)
  * Marginal relief at each surcharge threshold (50L / 1Cr / 2Cr / 5Cr)
  * 80CCD(2) auto-cap (10% old / 14% new of basic+DA)
  * Sec 206AA: 20% floor when PAN missing/invalid (with format validation)
  * Senior / super-senior basic exemption (old regime: 3L / 5L)
  * Regime lock once TDS applied for the FY
  * HRA city tier selector (incl. new 8-city metro list w.e.f. 1 Apr 2026)
  * Bonus-month catch-up TDS amount surfaced
  * Drift detection + Resync + Rollback buttons (TDS field write audit)
  * Auto-default remaining_months from FY + today
  * Employer perk aggregate cap (Rs 7.5L) info banner
  * Unique constraint on (employee, FY, company)

See README.md for design, limitations and CA-validation items.
""",
    "author": "Mrelate / LinkedERP",
    "website": "https://www.linkederp.com",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "hr_payroll",
        "l10n_in_hr_payroll",
    ],
    "data": [
        "security/tds_security.xml",
        "security/ir.model.access.csv",
        "data/tds_fy_2026_27_data.xml",
        "views/tds_config_views.xml",
        "views/tds_declaration_views.xml",
        "views/tds_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
