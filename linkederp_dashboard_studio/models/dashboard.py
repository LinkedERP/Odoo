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
