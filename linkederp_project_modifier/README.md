# LinkedERP Project Modifier

**Version:** 1.1.0 · **License:** LGPL-3 · **Depends:** `project`, `sale_project`, `hr_timesheet`

View and billing adjustments for projects and tasks, aligned with the timesheet and sales modifiers.

## Features in this release

- **Lock timesheets on completed orders.** A task's timesheet list becomes read-only once its own sale order or the project's sale order is marked completed (`x_studio_completed`), preventing time logging against closed work.
- **Scoped Sales Order Item.** The task's Sales Order Item field is restricted to the order lines of the project's sale order (`available_sale_line_domain`).
- **Followers on project form.** The project's message partners (`message_partner_ids`) are shown on the project form as avatar tags, next to Company.

## Views

- `project.task` form: hidden helper fields plus the completed-order read-only rule on timesheets.
- `project.project` form: followers field.
