import ast

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class LinkederpDashboard(models.Model):
    _name = "linkederp.dashboard"
    _description = "LinkedERP Dashboard"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    color = fields.Char(default="#2563eb")
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        help="Leave empty to make this dashboard available across companies.",
    )
    allowed_group_ids = fields.Many2many(
        "res.groups",
        "linkederp_dashboard_group_rel",
        "dashboard_id",
        "group_id",
        string="Visible to Groups",
        help="Leave empty to make this dashboard visible to all internal users.",
    )
    widget_ids = fields.One2many(
        "linkederp.dashboard.widget",
        "dashboard_id",
        string="Widgets",
        copy=True,
    )

    def _visible_to_current_user(self):
        user_groups = self.env.user.groups_id
        return self.filtered(
            lambda dashboard: not dashboard.allowed_group_ids
            or bool(dashboard.allowed_group_ids & user_groups)
        )

    @api.model
    def get_dashboard_payload(self, dashboard_id=False, date_from=False, date_to=False):
        dashboards = self.search([("active", "=", True)], order="sequence, name")
        if not dashboards and not dashboard_id:
            self.sudo()._ensure_default_sales_crm_dashboard()
            dashboards = self.search([("active", "=", True)], order="sequence, name")
        dashboards = dashboards._visible_to_current_user()

        if dashboard_id:
            dashboard = self.browse(int(dashboard_id)).exists()
            if not dashboard or dashboard.id not in dashboards.ids:
                raise AccessError(_("You do not have access to this dashboard."))
        else:
            dashboard = dashboards[:1]

        return {
            "dashboards": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description or "",
                    "color": item.color or "#2563eb",
                }
                for item in dashboards
            ],
            "dashboard": dashboard
            and {
                "id": dashboard.id,
                "name": dashboard.name,
                "description": dashboard.description or "",
                "color": dashboard.color or "#2563eb",
            }
            or False,
            "widgets": dashboard
            and [
                widget._get_payload(date_from=date_from, date_to=date_to)
                for widget in dashboard.widget_ids.filtered("active").sorted(
                    key=lambda item: (item.sequence, item.id)
                )
            ]
            or [],
        }

    @api.model
    def _ensure_default_sales_crm_dashboard(self):
        if self.search_count([]):
            return
        if "sale.order" not in self.env or "crm.lead" not in self.env:
            return

        dashboard = self.create(
            {
                "name": _("Sales & CRM Dashboard"),
                "sequence": 10,
                "description": _(
                    "LinkedERP starter dashboard for sales orders, revenue, pipeline, and opportunity performance."
                ),
                "color": "#2563eb",
            }
        )

        specs = [
            {
                "name": _("Confirmed Revenue"),
                "sequence": 10,
                "widget_type": "kpi",
                "model": "sale.order",
                "value_mode": "sum",
                "measure": "amount_total",
                "date": "date_order",
                "domain_filter": "[('state', 'in', ['sale', 'done'])]",
                "color": "#2563eb",
                "help_text": _("Total confirmed sales order value in the selected period."),
            },
            {
                "name": _("Confirmed Orders"),
                "sequence": 20,
                "widget_type": "kpi",
                "model": "sale.order",
                "value_mode": "count",
                "date": "date_order",
                "domain_filter": "[('state', 'in', ['sale', 'done'])]",
                "color": "#059669",
                "help_text": _("Number of confirmed sales orders in the selected period."),
            },
            {
                "name": _("Open Opportunities"),
                "sequence": 30,
                "widget_type": "kpi",
                "model": "crm.lead",
                "value_mode": "count",
                "date": "create_date",
                "domain_filter": "[('type', '=', 'opportunity'), ('active', '=', True)]",
                "color": "#7c3aed",
                "help_text": _("Active opportunities created in the selected period."),
            },
            {
                "name": _("Expected Pipeline"),
                "sequence": 40,
                "widget_type": "kpi",
                "model": "crm.lead",
                "value_mode": "sum",
                "measure": "expected_revenue",
                "date": "create_date",
                "domain_filter": "[('type', '=', 'opportunity'), ('active', '=', True)]",
                "color": "#db2777",
                "help_text": _("Expected revenue from active opportunities created in the selected period."),
            },
            {
                "name": _("Sales by Month"),
                "sequence": 50,
                "widget_type": "line",
                "model": "sale.order",
                "value_mode": "sum",
                "measure": "amount_total",
                "groupby": "date_order",
                "groupby_interval": "month",
                "date": "date_order",
                "domain_filter": "[('state', 'in', ['sale', 'done'])]",
                "limit": 12,
                "color": "#2563eb",
            },
            {
                "name": _("Top Customers"),
                "sequence": 60,
                "widget_type": "bar",
                "model": "sale.order",
                "value_mode": "sum",
                "measure": "amount_total",
                "groupby": "partner_id",
                "date": "date_order",
                "domain_filter": "[('state', 'in', ['sale', 'done'])]",
                "limit": 8,
                "color": "#059669",
            },
            {
                "name": _("Pipeline by Stage"),
                "sequence": 70,
                "widget_type": "bar",
                "model": "crm.lead",
                "value_mode": "sum",
                "measure": "expected_revenue",
                "groupby": "stage_id",
                "date": "create_date",
                "domain_filter": "[('type', '=', 'opportunity'), ('active', '=', True)]",
                "limit": 10,
                "color": "#7c3aed",
            },
            {
                "name": _("Opportunities by Salesperson"),
                "sequence": 80,
                "widget_type": "table",
                "model": "crm.lead",
                "value_mode": "sum",
                "measure": "expected_revenue",
                "groupby": "user_id",
                "date": "create_date",
                "domain_filter": "[('type', '=', 'opportunity'), ('active', '=', True)]",
                "limit": 10,
                "color": "#db2777",
            },
        ]

        Widget = self.env["linkederp.dashboard.widget"]
        for spec in specs:
            model = self._dashboard_model(spec["model"])
            if not model:
                continue
            vals = {
                "dashboard_id": dashboard.id,
                "name": spec["name"],
                "sequence": spec["sequence"],
                "widget_type": spec["widget_type"],
                "model_id": model.id,
                "value_mode": spec["value_mode"],
                "domain_filter": spec["domain_filter"],
                "limit": spec.get("limit", 8),
                "color": spec["color"],
                "help_text": spec.get("help_text", ""),
            }
            measure = self._dashboard_field(model.model, spec.get("measure"))
            groupby = self._dashboard_field(model.model, spec.get("groupby"))
            date_field = self._dashboard_field(model.model, spec.get("date"))
            if spec.get("measure") and not measure:
                continue
            if spec.get("groupby") and not groupby:
                continue
            if measure:
                vals["measure_field_id"] = measure.id
            if groupby:
                vals["groupby_field_id"] = groupby.id
                vals["groupby_interval"] = spec.get("groupby_interval", "month")
            if date_field:
                vals["date_field_id"] = date_field.id
            Widget.create(vals)

    @api.model
    def _dashboard_model(self, model_name):
        return self.env["ir.model"].search([("model", "=", model_name)], limit=1)

    @api.model
    def _dashboard_field(self, model_name, field_name):
        if not field_name:
            return self.env["ir.model.fields"]
        return self.env["ir.model.fields"].search(
            [("model", "=", model_name), ("name", "=", field_name)],
            limit=1,
        )

    @api.model
    def action_open_records(self, model_name, domain=False):
        if model_name not in self.env:
            raise UserError(_("Model %s is not available.") % model_name)

        target_model = self.env[model_name]
        target_model.check_access_rights("read")

        if not domain:
            parsed_domain = []
        elif isinstance(domain, str):
            parsed_domain = ast.literal_eval(domain)
        else:
            parsed_domain = domain

        model_label = self.env["ir.model"]._get(model_name).display_name
        return {
            "type": "ir.actions.act_window",
            "name": model_label,
            "res_model": model_name,
            "view_mode": "list,form,pivot,graph",
            "domain": parsed_domain,
            "target": "current",
        }

    def action_view_dashboard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "name": self.name,
            "tag": "linkederp_dashboard_studio.dashboard_action",
            "params": {"dashboard_id": self.id},
        }
