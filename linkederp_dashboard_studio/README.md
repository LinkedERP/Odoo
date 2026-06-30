# LinkedERP Dashboard Studio

Native Odoo 19 dashboard builder MVP for LinkedERP.

## What This Includes

- A new Odoo app: **Dashboards**
- A modern Owl dashboard screen inside Odoo
- Configurable widgets for KPI, bar, line, pie, and table views
- A starter **Sales & CRM Dashboard**
- Global date filters
- Drill-down from KPIs, charts, and tables into the underlying Odoo records
- Odoo-native security: reads data through the ORM and respects normal access rules

## Installation On Odoo.sh

1. Copy the `linkederp_dashboard_studio` folder into the custom addons repository used by the Odoo.sh branch.
2. Commit and push the branch.
3. Wait for the Odoo.sh build to complete.
4. In Odoo, enable developer mode and update the Apps list.
5. Install **LinkedERP Dashboard Studio**.
6. Give configuration users the **LinkedERP Analytics / Dashboard Manager** group.

## First Demo Path

Open **Dashboards** from the Odoo menu. The starter Sales & CRM dashboard should show:

- Confirmed Revenue
- Confirmed Orders
- Open Opportunities
- Expected Pipeline
- Sales by Month
- Top Customers
- Pipeline by Stage
- Opportunities by Salesperson

## Notes

This first module depends on `sale_management` and `crm` so the demo has useful dashboards immediately. The next evolution should split the product into:

- `linkederp_dashboard_studio`: generic dashboard builder
- `linkederp_dashboard_sales`: Sales dashboard pack
- `linkederp_dashboard_inventory`: Inventory dashboard pack
- `linkederp_dashboard_accounting`: Accounting dashboard pack
