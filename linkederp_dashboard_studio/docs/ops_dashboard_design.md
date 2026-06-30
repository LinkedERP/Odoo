# Ops Performance Dashboard — Design (rows 1 & 2)

Native re-build of the Power BI **"Weekly OPS Review"** page inside
`linkederp_dashboard_studio`. Follows the same computed-dashboard pattern as the
AI Generated Leads dashboard: a dashboard detected by name, with all numbers
computed live in Python. Ops logic lives in its own file
(`models/ops_dashboard.py`) so it does not tangle with `dashboard.py`.

Source PBIX: `Daily Ops Review.pbix` (main page "OPS Weekly Review").
Scope of this build: **rows 1 & 2 only** (TIME ENTRY, DETAILS, RESOURCE PLANNING).
Rows 3-4 (PROJECT REVIEW, SLA) are deliberately out of scope for now.

## Core rule: everything is per USER, expected hours per DEFAULT company

One `res.users` can have several `hr.employee` records (one per subsidiary).

- **Numerators** (hours logged, billable hours, planned hours) roll up **all of a
  user's hours across every company**, grouped by `user_id`.
- **Denominator** (expected hours) comes from **only the employee in the user's
  default company** (`res.users.company_id`). That employee's resource calendar,
  minus their leaves and that company's public holidays, defines expected hours.

This is why multi-subsidiary people legitimately exceed 100% (Coverage 101%,
Billability 117/133/155% in the source). Expected hours are computed by Odoo's
own `hr.employee._get_work_days_data_batch(start, end, compute_leaves=True)`,
which nets out both public holidays and personal leave (personal leaves are
stored as `resource.calendar.leaves` on the employee's resource).

## Population

One row per active user that has an active employee in their **default company**
with a working calendar ("delivery employees"). Easy to narrow to specific
departments later.

## Metric definitions

For a user and a week window:

| Symbol | Meaning |
|---|---|
| E  | Expected hours = default-company employee calendar hours that week, minus leaves & holidays |
| EB | Expected billable = `0.75 × E` |
| L  | Logged hours = user's project timesheet `unit_amount`, all companies, `date` in week |
| B  | Billable hours = the L hours where `timesheet_invoice_type != 'non_billable'` |
| P  | Planned hours = user's `planning.slot.allocated_hours`, all companies, `start_datetime` in week |

- **Pass Rate** (last week) = on-time entries ÷ total entries · on-time = entry
  `create_date` on/before the Monday of the current week · **counted as % of entries**
- **Coverage** (last week) = `L ÷ E`
- **Billability** (last week) = `B ÷ EB`
- **Planning** (this week) = `P ÷ EB`
- **vs prior week** = this value − prior week's value (percentage points), ▲ green / ▼ red / • grey

## Time windows (anchor = today, or `date_to` if supplied)

- **This week** = ISO week containing the anchor (Monday start).
- **Last completed week** = the week before this week → Pass / Coverage / Billability cards & DETAILS.
- **Planning** uses **this week**.
- **Billability chart** = last 8 completed weeks (W-7 … W0).
- **Planning chart** = this week + next 7 (W0 … W+7).
- Weekly bars are **team aggregates**: ΣB ÷ ΣEB (billability), ΣP ÷ ΣEB (planning).
  The avg badge = mean of the 8 weekly bars.

## Colour thresholds (good / warn / bad)

- Pass Rate & Coverage: green ≥ 100, amber ≥ 90, else red.
- Billability & Planning: green ≥ 85 (target), amber ≥ 70, else red.

## Widgets & layout (12-col grid)

1. `section` **TIME ENTRY** (span 6) — note "target: 100% pass · 100% coverage"
2. `section` **DETAILS** (span 6) — note "last week — pass · coverage · billability  ·  this week — planning"
3. `kpi` **Pass rate this week** (span 3) + delta
4. `kpi` **Coverage this week** (span 3) + delta
5. `matrix` **Details** (span 6) — per user: % Pass, % Coverage, % Billability, % Planning, colour-coded cells, sorted worst-billability first
6. `section` **RESOURCE PLANNING** (span 12) — note "target: 85%"
7. `column` **Billability — last 8 weeks** (span 6) — per-bar colour, target line, avg badge
8. `column` **Planning — next 8 weeks** (span 6) — per-bar colour, target line, avg badge

## Front-end additions (all additive, backward-compatible)

- KPI: optional `widget.delta` sub-line (▲/▼ + tone colour).
- Matrix: optional `row.tones[colKey]` → conditional cell colour.
- Column: optional `point.color` per bar, `widget.target` dashed line, `widget.badge` in header.
- New `section` widget type: slim full-width/spanned band header.

## Module wiring

- `models/ops_dashboard.py` (`_inherit = linkederp.dashboard`).
- `get_dashboard_payload` gets an Ops branch (parallel to the AI branch).
- `_ensure_packaged_dashboards` also ensures the Ops dashboard.
- Manifest depends additionally on `hr_timesheet` and `planning`.

## Known limitations / future

- Team slicer skipped for v1 (the 404 Found / Core X / … teams do not exist in
  the dev DB; source unknown).
- Live computation (~17 weeks × per-employee calendar calls). Fine for a weekly
  review; can be pre-materialised into a weekly summary table later if slow.
- Rows 3-4 (Project Review margins, SLA helpdesk ageing) to follow.
