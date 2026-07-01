# LinkedERP Sales Modifier

**Version:** 1.0.4 · **License:** LGPL-3 · **Depends:** `sale`, `sale_timesheet`

Keeps completed sale orders out of the way in day-to-day views and simplifies order locking.

## Features in this release

- **Open/Complete order filters.** New **"Open Orders"** and **"Complete Order"** filters (on `x_studio_completed`) added to both the Sales Order and Quotation search views.
- **Default to open orders.** The Sales Orders and Quotations actions default to showing open (uncompleted) records. Because this is applied via `context` (not `domain`), users can clear the filter to see completed orders when needed.
- **Unconditional lock/unlock.** `action_lock` / `action_unlock` are overridden to lock or unlock an order regardless of its invoice status.
