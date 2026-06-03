# Mrelate Payroll Expense Integration

Small, isolated extension of Odoo's standard `hr_payroll_expense` bridge that lets
payroll **refresh approved, reimbursable expenses into an existing draft payslip**
— without manual linking.

## Why this module exists

Confirmed by UAT on the DEV database:

* The **standard** Expense → Payslip flow works **only** when the expense is
  approved and marked *"Reimburse in Next Payslip"* **before** the payslip is
  created. Odoo gathers expenses at **payslip-creation** time.
* If a **draft payslip already exists** and the expense is approved **later**,
  clicking **Compute Sheet** does **not** pull the expense in. `compute_sheet`
  only recomputes lines from already-attached `expense_ids`; it does not
  re-gather.
* HR/payroll were therefore forced to link records by hand — not acceptable as a
  business process.

This module closes that gap safely.

## What it does

`hr.payslip` gains:

| Member | Purpose |
| --- | --- |
| `_get_refundable_expense_domain()` | The eligibility domain (see below). |
| `_get_refundable_expenses()` | Eligible expenses for this slip (empty if not draft). |
| `_refresh_payslip_expenses()` | Attaches eligible expenses to each **draft** slip via the standard `expense_ids` relation. Idempotent. |
| `action_refresh_expenses()` | **Refresh Expenses** button. Draft-only; recomputes; posts an audit note to chatter. |
| `compute_sheet()` (override) | For **draft** slips, refreshes eligible expenses first, then computes. Non-draft slips are untouched. |

### Eligibility domain

An expense is pulled into a draft payslip when **all** of these hold:

* `employee_id`  = payslip employee
* `company_id`   = payslip company
* `payment_mode` = `own_account` (paid by employee)
* `state`        = `approved`
* `refund_in_payslip` = `True` ("Reimburse in Next Payslip")
* `payslip_id`   = `False` (not already on a payslip)
* `account_move_id` = `False` (no journal entry yet)

This mirrors native `hr_payroll_expense` gather logic and adds two defensive
guards (`company_id`, `account_move_id`). It is **not** date-filtered on purpose:
"Reimburse in Next Payslip" means a late-approved expense from an earlier period
must still be reimbursed, not silently dropped. Attached expenses stay fully
visible on the draft slip for review before validation.

## Safety guarantees

* Acts **only** on payslips in state `draft`.
* **Never** posts a payslip, posts an expense, creates a payment, or creates a
  journal entry / account move.
* **Never** detaches expenses and **never** touches expenses already linked to
  another payslip (`payslip_id = False` in the domain) → no double reimbursement.
* Fully **idempotent**: running refresh / compute repeatedly never duplicates.
* Adds **no** new models and **no** new access rules; runs under the user's
  existing payslip rights.
* Does not modify any standard Odoo source file.

## A-only vs A+B (button vs compute auto-refresh)

Shipped with **both**, and **A+B is recommended**:

* **A — Refresh Expenses button:** explicit corrective control with a chatter
  audit note (count, total, expense IDs). Always safe.
* **B — `compute_sheet` auto-refresh (draft only):** payroll users naturally
  click *Compute*; this makes Compute also pull late-approved expenses. It is
  safe because it is draft-only, idempotent, posts nothing, and leaves non-draft
  payslips unchanged.

If you prefer no implicit change on Compute, remove the `compute_sheet` override
and keep only the button (A-only).

## Dependencies

`hr_payroll_expense` (which itself pulls `hr_payroll` + `hr_expense`).

## Compatibility / notes

* Built and validated against Odoo **19.0**.
* The standard expense **approval** in this DB requires a 100% analytic
  distribution (a company-2 configuration). That is a separate prerequisite and
  is out of scope for this module.
