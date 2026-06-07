# India Payroll Suite — Mrelate / LinkedERP

Customer-installable wrapper that turns the standard Odoo 19 India payroll into
a complete SME-grade payroll system: TDS engine that's actually current for
FY 2026-27, dashboards, a Form 12BB declaration printout, and a one-click
**Monthly Payroll Run** wizard.

Designed for Indian SMEs with 20–100 employees. Resold by LinkedERP as a
managed product.

## What's in the bundle

| Module | What it does |
|---|---|
| **`mrelate_payroll_tds`** | Dual-regime tax engine (new+old), marginal relief, age-based exemption, sec 206AA, employee declaration workflow, monthly TDS computation, write-back to `hr.version.l10n_in_tds`. |
| **`mrelate_payroll_expense_integration`** | Closes the late-approval expense gap: a *Refresh Expenses* button on draft payslips + auto-refresh on Compute Sheet. Never posts. |
| **`mrelate_payroll_suite`** | This module. Dashboards (TDS register + payroll-cost graph/pivot), Form-12BB-style declaration printout, and the **Monthly Payroll Run** wizard. |

Install order: `mrelate_payroll_tds` → `mrelate_payroll_expense_integration` → `mrelate_payroll_suite`.
Dependencies are declared correctly so Apps → Install on the suite pulls the others in.

## What the Monthly Payroll Run wizard does (the "minimal HR intervention" promise)

For each active employee in the selected company that has an India contract:

1. **Ensures a TDS declaration exists** for the current FY (auto-creates as DRAFT if missing).
2. **Refreshes the salary projection** from existing payslips (paid YTD, current month, projected remaining, annual Basic+DA).
3. If the declaration is **already approved**, **re-applies** the monthly TDS to `hr.version.l10n_in_tds` (snapshotting the prior value for rollback).
4. **Creates a draft payslip** for the period (skipped if one already exists in validated state).
5. **Auto-fills the worked-days line** from the version's resource calendar (Attendance type, full working days).
6. Runs **compute_sheet**, which (via the expense module) **pulls in any newly approved reimbursable expenses**.
7. Logs everything to a chatter audit and shows a summary table.

**HR's only manual step:** review the draft payslips and click **Confirm/Validate**.

Safety: never validates a payslip, never creates accounting entries, never touches employees outside the selected company.

## Branding / packaging notes

- All user-facing strings now read **"India Payroll TDS"** (not "Mrelate India Payroll TDS"). The Python module names retain the `mrelate_` prefix for stability; downstream customers won't see them in the UI.
- All four India states with PT rule parameters (KA / MH / GJ / WB / AP) work out-of-the-box via the version's `pt_rule_parameter_id` — set per company / per state.
- The TDS rule on the company's structure is overridden to **cap at GROSS** so a misconfigured TDS field can never produce a negative net.
- License: LGPL-3. Resell freely; modify and redistribute under the same terms.

## What the suite does NOT do (intentional Phase-1 scope)

- Doesn't validate payslips or post accounting entries.
- Doesn't generate Form 24Q XML for TDS return upload (manual export from the dashboard).
- Doesn't generate the **government-prescribed Form 16 Part B** — the standard l10n_in_hr_payroll Form 16 ships with stale FY 2024-25 rates; use BOSS / IT portal until we ship a Form 16 wrapper in v1.1.
- Doesn't model perquisites under sec 17(2) — flagged in the declaration's banner if the employer-perk aggregate exceeds ₹7.5L.
- Doesn't auto-handle ESOP vesting, sec 89(1) arrears relief, or Form 12B-driven previous-employer reconciliation (declaration accepts the numbers; engine uses them).

## Customer-side install (3 steps)

1. **Push** the three module folders to the customer's Odoo.sh dev branch.
2. **Wait** for the build to go green.
3. **Apps → Update Apps List → search "India Payroll Suite" → Install.**
   Assign yourself to *TDS: Payroll Reviewer* under Settings → Users.

Then from the **Payroll → India TDS** menu:
- Open **Monthly Payroll Run** every month-end → click Run.
- Open **TDS Dashboard** for a quick view by department / regime / TDS band.
- Open **Payroll Cost Dashboard** for monthly gross/net trends.

## Roadmap (we'll ship as customer demand justifies)

- v1.1: Form 16 Part B generator with current-year tax rates.
- v1.2: Sec 89(1) Form 10E helper.
- v1.3: Perquisite computation (RFA, ESOP, company car) per Rule 3.
- v1.4: 24Q quarterly TXT generator for TIN-NSDL upload.
- v1.5: Employee self-service portal for declaration entry.
