# LinkedERP Helpdesk Modifier

**Version:** 1.1.0 · **License:** LGPL-3 · **Depends:** `helpdesk`, `helpdesk_sale`, `mail`, `hr_timesheet`, `helpdesk_sale_timesheet`

Adds automated follow-up reminders for stale helpdesk tickets and links tickets to project tasks and sale order lines for billing.

## Features in this release

- **Unanswered-ticket email reminders.** A daily scheduled action finds open, assigned tickets with no support reply for **3+ working days** and emails a reminder to the assigned user.
  - **Per-user working-day calendar.** The 3-day threshold counts working days only, skipping weekends and public holidays taken from the assignee's resource calendar (falling back to the company calendar).
  - **No spam.** A ticket is not reminded again until another 3 working days pass. The send date is recorded via direct SQL so it does not bump `write_date` and re-trigger the ticket.
  - **Chatter trail.** Each reminder is also posted as an internal note on the ticket.
- **Project Manager on Helpdesk Team.** New `project_manager_id` field on the team, scoped to internal users of the team's company.
- **Ticket → Task roll-up (A05).** Teams define a default **Roll-up Task**; tickets inherit it (editable per ticket) so ticket effort is visible at task level.
- **SO line restriction.** The ticket's Sales Order Item is scoped to the linked sale order's own lines, and timesheets on the ticket become read-only once the sale order is marked completed (`x_studio_completed`).

## Configuration

- Scheduled action: **Settings → Technical → Scheduled Actions → "Helpdesk: Send Unanswered Ticket Reminders"** (runs daily). Default next-run is 01:00 SAST (23:00 UTC).
- Email template: **"Helpdesk: Unanswered Ticket Reminder"** — customise subject/body under Technical → Email → Templates.
- Reminder threshold is `REMINDER_DAYS = 3` in `models/helpdesk_ticket.py`.

## Tests

`tests/test_helpdesk_ticket_reminder.py` covers the working-day threshold, public-holiday handling, and reminder gating.
