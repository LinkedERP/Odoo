# Deploy & UAT — Mrelate Payroll Expense Integration

## 1. Files in this module

```
mrelate_payroll_expense_integration/
├── __init__.py
├── __manifest__.py
├── README.md
├── DEPLOY_AND_UAT.md
├── models/
│   ├── __init__.py
│   └── hr_payslip.py          # methods + button + compute_sheet override
└── views/
    └── hr_payslip_views.xml    # "Refresh Expenses" button on the draft payslip form
```

No security file is needed (no new models / no new access rules).

## 2. Deployment (Odoo.sh)

> Claude cannot install modules; a human must deploy. The MCP write tools are
> read-only for code and cannot install/upgrade apps.

### Option A — Git (recommended on Odoo.sh)
1. Commit the `mrelate_payroll_expense_integration/` folder to the repository
   branch backing the **development** build (`19.0`).
2. Push. Odoo.sh rebuilds the branch.
3. In the rebuilt DB: **Apps → Update Apps List**, search
   *"Mrelate Payroll Expense Integration"*, click **Install**.

### Option B — Manual upload (Odoo.sh editor / addons path)
1. Upload the folder into the branch's addons path.
2. Restart / rebuild.
3. **Apps → Update Apps List → Install**.

### Upgrade after code changes
**Apps → (this module) → Upgrade**, or `-u mrelate_payroll_expense_integration`.

## 3. How payroll uses it (post-install)

1. Open a **Draft** payslip.
2. Click **Refresh Expenses** (next to *Compute Sheet*), **or** just click
   **Compute Sheet** — both pull any newly approved reimbursable expenses.
3. The **EXPENSES** line updates; the chatter logs what was added.

## 4. UAT results (DEV — pre-deployment logic validation)

Scope: DEV only · Company 2 (Mrelate) · Employee 428 (TEST Payroll Dummy) ·
July 2026 draft payslip **ID 3** · expenses **377** and **378** (₹1,000 each).

> The module was not yet installed at validation time, so the module's **exact
> algorithm** (eligibility search → `expense_ids` link → `compute_sheet`) was
> executed through the MCP tools to prove the data outcome. After deployment the
> button / Compute perform these steps automatically. State guards
> (`UserError` on non-draft, button hidden on non-draft) are validated by code
> review.

| # | Test case | Expected | Result |
| --- | --- | --- | --- |
| 1 | Draft slip 3 + late-approved unlinked expense 378 → refresh | 378 attaches, EXPENSES ₹1,000→₹2,000, net ₹134,450→₹135,450, `expense.payslip_id=3` | **PASS** |
| 2 | Refresh again with no new expenses | eligibility search returns `[]`, no change, no error | **PASS** |
| 3 | Expenses already linked to slip 3 → refresh slip 4 | not pulled (slip 4 stays `expenses_count=0`) | **PASS** |
| 4 | Non-draft slip (validated slip 2) | refresh blocked (`UserError`, button hidden, helper returns empty) | **PASS (by guard/review)** |
| 5 | No accounting/payment/posting | slips stay draft, no `move_id`, expenses `account_move_id=False`, not paid | **PASS** |

Idempotency: after attaching, a second eligibility search returned `[]` and a
recompute kept a **single** EXPENSES input (₹2,000) with `expenses_count=2` — no
duplication.

### Final DEV state after UAT
* Expense 377 → payslip 3; Expense 378 → payslip 3 (EXPENSES ₹2,000, net ₹135,450, **draft**).
* Payslip 4 ("UAT Auto-Pull Test") → draft, no expenses (net ₹138,450).
* No journal entry / payment / posting created by this work. (Payslip 2's draft
  accounting move 10630 pre-existed from an earlier June validation and was not
  touched.)

## 5. Rollback

Uninstall the module (**Apps → Uninstall**) or remove the folder and update the
apps list. It adds no columns/tables of its own, so uninstall is clean. Existing
`expense_ids` links created while installed remain valid standard Odoo data.
