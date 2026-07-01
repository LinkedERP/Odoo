# Timesheet LinkedERP Modifier

**Version:** 1.1.0 · **License:** AGPL-3 · **Depends:** `account`, `hr_timesheet`, `sale_timesheet`, `helpdesk_sale_timesheet`

Adjusts timesheet (`account.analytic.line`) behaviour so time logged through projects, tasks and helpdesk tickets stays consistent with company boundaries and open sales orders.

## Features in this release

- **Company guard on timesheets.** A timesheet can only be logged on a project that belongs to the currently selected company. Mismatches are blocked both on save (`ValidationError`) and live in the form view (onchange warning), clearing the invalid project.
- **Open-order-only project selector.** The Project field hides projects whose re-invoice sale order is already completed (`x_is_reinvoice_completed`). Non-managers additionally only see projects they are a member of or that are employee/portal visible.
- **Open-order-only SO line selector.** The billable Sales Order Item field excludes lines belonging to completed sale orders (`x_studio_completed`), and is scoped per record to the customer's own order lines.
- **Helpdesk → Task time roll-up (A05).** A single timesheet line may link to **both** a task and a helpdesk ticket. Ticket time surfaces at task level (and ticket level) while still being counted once at project level — no double counting on dashboards. The native mutual-exclusion between task and ticket is relaxed for this.
- **List/form view tweaks.** Task and ticket selectors on timesheet lists use no-create/no-open options and per-row SO line domains for cleaner, safer selection.

## Notes

- `models/account_currency.py` (project-driven invoice company/currency onchange) ships but is **not** wired into `models/__init__.py` — it is intentionally inactive.
