import ast
from datetime import date, datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression


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
        user_groups = self._current_user_groups()
        if not user_groups:
            return self
        return self.filtered(
            lambda dashboard: not dashboard.allowed_group_ids
            or bool(dashboard.allowed_group_ids & user_groups)
        )

    def _current_user_groups(self):
        user = self.env.user
        if "groups_id" in user._fields:
            return user.groups_id
        if "group_ids" in user._fields:
            return user.group_ids
        return self.env["res.groups"]

    @api.model
    def get_dashboard_payload(self, dashboard_id=False, date_from=False, date_to=False, filters=False):
        self.sudo()._ensure_packaged_dashboards()
        dashboards = self.search([("active", "=", True)], order="sequence, name")
        dashboards = dashboards._visible_to_current_user()

        if dashboard_id:
            dashboard = self.browse(int(dashboard_id)).exists()
            if not dashboard or dashboard.id not in dashboards.ids:
                raise AccessError(_("You do not have access to this dashboard."))
        else:
            dashboard = dashboards[:1]

        filter_domain = dashboard._crm_filter_domain(filters) if dashboard else []
        widgets = []
        if dashboard:
            widgets = [
                widget._get_payload(
                    date_from=date_from,
                    date_to=date_to,
                    extra_domain=filter_domain if widget.model_name == "crm.lead" else False,
                )
                for widget in dashboard.widget_ids.filtered("active").sorted(
                    key=lambda item: (item.sequence, item.id)
                )
            ]
            if dashboard._is_ai_generated_leads_dashboard():
                widgets = dashboard._ai_generated_lead_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )

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
                "is_ai_generated_leads": dashboard._is_ai_generated_leads_dashboard(),
            }
            or False,
            "widgets": widgets,
            "crm_filters": dashboard._dashboard_crm_filter_options(date_from=date_from, date_to=date_to)
            if dashboard
            else {"enabled": False},
        }

    @api.model
    def _ensure_packaged_dashboards(self):
        self._ensure_default_sales_crm_dashboard()
        self._ensure_ai_generated_leads_dashboard()

    @api.model
    def _ensure_default_sales_crm_dashboard(self):
        if self.search([("name", "=", "Sales & CRM Dashboard")], limit=1):
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
    def _ensure_ai_generated_leads_dashboard(self):
        if self.search([("name", "=", "AI Generated Leads Performance")], limit=1):
            return
        if "crm.lead" not in self.env:
            return
        self.create(
            {
                "name": _("AI Generated Leads Performance"),
                "sequence": 20,
                "description": _(
                    "Track AI-sourced CRM lead volume, calling work, meetings, suitability, ownership, and pipeline movement."
                ),
                "color": "#0f766e",
            }
        )

    def _is_ai_generated_leads_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == "ai generated leads performance"

    def _ai_source_domain(self):
        return expression.OR(
            [
                [("source_id.name", "ilike", "AI Generated")],
                [("source_id.name", "ilike", "AI-Generated")],
                [("source_id.name", "ilike", "AIGenerated")],
            ]
        )

    def _crm_filter_domain(self, filters=False):
        filters = filters or {}
        domain = []
        for key, field_name in (
            ("campaign_id", "campaign_id"),
            ("user_id", "user_id"),
            ("team_id", "team_id"),
            ("stage_id", "stage_id"),
        ):
            value = filters.get(key)
            if value:
                domain.append((field_name, "=", int(value)))
        return domain

    def _ai_base_domain(self, date_from=False, date_to=False, filters=False, extra_domain=False):
        domains = [self._ai_source_domain()]
        date_domain = []
        if date_from:
            date_domain.append(("create_date", ">=", "%s 00:00:00" % date_from))
        if date_to:
            date_domain.append(("create_date", "<=", "%s 23:59:59" % date_to))
        if date_domain:
            domains.append(date_domain)
        filter_domain = self._crm_filter_domain(filters)
        if filter_domain:
            domains.append(filter_domain)
        if extra_domain:
            domains.append(extra_domain)
        return expression.AND(domains)

    def _ai_sum(self, domain, field_name):
        rows = self._ai_lead_model().read_group(
            domain,
            ["%s:sum" % field_name],
            [],
            lazy=False,
        )
        return rows and rows[0].get(field_name, 0) or 0

    def _ai_rate(self, numerator, denominator):
        if not denominator:
            return 0
        return round((numerator / denominator) * 100, 1)

    def _ai_widget(
        self,
        widget_id,
        name,
        widget_type,
        value,
        domain,
        color,
        measure,
        help_text="",
        points=False,
        rows=False,
        columns=False,
        groupby="",
        value_format="number",
        span=False,
    ):
        return {
            "id": widget_id,
            "name": name,
            "type": widget_type,
            "model": "crm.lead",
            "mode": "computed",
            "measure": measure,
            "groupby": groupby,
            "color": color,
            "help": help_text,
            "value": float(value or 0),
            "format": value_format,
            "domain": self._json_safe(domain),
            "points": points or [],
            "rows": rows or [],
            "columns": columns or [],
            "span": span or False,
            "error": False,
        }

    def _ai_point(self, label, value, domain):
        return {
            "label": label,
            "value": float(value or 0),
            "domain": self._json_safe(domain),
        }

    def _ai_group_points(self, domain, groupby, measure=False, limit=12):
        Lead = self._ai_lead_model()
        group_field = groupby.split(":", 1)[0]
        fields_to_read = [group_field]
        if measure:
            fields_to_read.append("%s:sum" % measure)
        rows = Lead.read_group(
            domain,
            fields_to_read,
            [groupby],
            lazy=False,
            limit=limit,
        )

        points = []
        for row in rows:
            raw_label = row.get(group_field, row.get(groupby))
            if isinstance(raw_label, (list, tuple)) and len(raw_label) >= 2:
                label = raw_label[1] or _("Undefined")
            elif raw_label in (False, None, ""):
                label = _("Undefined")
            else:
                label = str(raw_label)
            value = row.get(measure, 0) if measure else row.get("__count", 0)
            points.append(self._ai_point(label, value, row.get("__domain", domain)))

        if ":" in groupby:
            return points
        return sorted(points, key=lambda item: item["value"], reverse=True)

    def _ai_lead_model(self):
        return self.env["crm.lead"].with_context(active_test=False)

    def _ai_count(self, domain):
        return self._ai_lead_model().search_count(domain)

    def _ai_average_age_days(self, domain):
        leads = self._ai_lead_model().search(domain, limit=2000)
        today = fields.Date.context_today(self)
        ages = []
        for lead in leads:
            created = fields.Date.to_date(lead.create_date)
            if created:
                ages.append((today - created).days)
        if not ages:
            return 0
        return round(sum(ages) / len(ages), 1)

    def _ai_matrix_rows(self, base_domain, groupby, limit=12):
        groups = self._ai_group_points(base_domain, groupby, limit=limit)
        rows = []
        for group in groups:
            group_domain = group["domain"]
            generated = self._ai_count(group_domain)
            worked_domain = expression.AND([group_domain, [("x_studio_call_outcome", "!=", False)]])
            meeting_domain = expression.AND(
                [
                    group_domain,
                    [
                        "|",
                        ("x_studio_call_outcome", "=", "Meeting Set"),
                        ("x_studio_meeting_date", "!=", False),
                    ],
                ]
            )
            lost_domain = expression.AND(
                [group_domain, ["|", ("won_status", "=", "lost"), ("active", "=", False)]]
            )
            open_domain = expression.AND([group_domain, [("active", "=", True)]])
            worked = self._ai_count(worked_domain)
            meetings = self._ai_count(meeting_domain)
            lost = self._ai_count(lost_domain)
            rows.append(
                {
                    "label": group["label"],
                    "domain": self._json_safe(group_domain),
                    "generated": generated,
                    "worked_rate": self._ai_rate(worked, generated),
                    "meetings": meetings,
                    "meeting_rate": self._ai_rate(meetings, generated),
                    "lost": lost,
                    "lost_rate": self._ai_rate(lost, generated),
                    "pipeline": self._ai_sum(open_domain, "expected_revenue"),
                }
            )
        return rows

    def _ai_week_points(self, domain, limit=12):
        leads = self._ai_lead_model().search(domain, limit=5000, order="create_date asc")
        buckets = {}
        for lead in leads:
            created = fields.Datetime.to_datetime(lead.create_date)
            if not created:
                continue
            week_start = created.date() - timedelta(days=created.weekday())
            bucket = buckets.setdefault(
                week_start,
                {
                    "label": _("Wk %s") % ("%02d" % week_start.isocalendar()[1]),
                    "value": 0,
                    "domain": expression.AND(
                        [
                            domain,
                            [
                                ("create_date", ">=", "%s 00:00:00" % fields.Date.to_string(week_start)),
                                (
                                    "create_date",
                                    "<=",
                                    "%s 23:59:59" % fields.Date.to_string(week_start + timedelta(days=6)),
                                ),
                            ],
                        ]
                    ),
                },
            )
            bucket["value"] += 1
        return [
            self._ai_point(bucket["label"], bucket["value"], bucket["domain"])
            for _, bucket in sorted(buckets.items())[-limit:]
        ]

    def _ai_campaign_meeting_turnover_points(self, meeting_domain, limit=12):
        points = self._ai_group_points(meeting_domain, "campaign_id", limit=limit)
        return sorted(points, key=lambda point: point["value"], reverse=True)

    def _ai_call_outcome_points(self, worked_domain):
        groups = [
            (
                _("Meeting Set"),
                [("x_studio_call_outcome", "=", "Meeting Set")],
            ),
            (
                _("In Progress"),
                [("x_studio_call_outcome", "in", ["Call Later", "Send more Info", "Future Interest"])],
            ),
            (
                _("Not Suitable"),
                [("x_studio_call_outcome", "in", ["Contact Not a Fit", "Company Not a fit"])],
            ),
            (
                _("Unreachable"),
                [("x_studio_call_outcome", "=", "Unable to make Contact")],
            ),
        ]
        points = []
        for label, extra_domain in groups:
            bucket_domain = expression.AND([worked_domain, extra_domain])
            points.append(self._ai_point(label, self._ai_count(bucket_domain), bucket_domain))
        return points

    def _ai_generated_lead_widgets(self, date_from=False, date_to=False, filters=False):
        base_domain = self._ai_base_domain(date_from=date_from, date_to=date_to, filters=filters)
        generated = self._ai_count(base_domain)

        open_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[("active", "=", True)],
        )
        open_count = self._ai_count(open_domain)

        worked_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[("x_studio_call_outcome", "!=", False)],
        )
        worked = self._ai_count(worked_domain)

        meeting_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[
                "|",
                ("x_studio_call_outcome", "=", "Meeting Set"),
                ("x_studio_meeting_date", "!=", False),
            ],
        )
        meetings = self._ai_count(meeting_domain)

        not_called_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[("x_studio_call_outcome", "=", False)],
        )
        not_called = self._ai_count(not_called_domain)

        lost_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=["|", ("won_status", "=", "lost"), ("active", "=", False)],
        )
        lost = self._ai_count(lost_domain)

        qualified_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[
                ("x_studio_call_outcome", "in", ["Meeting Set", "Send more Info", "Call Later", "Future Interest"])
            ],
        )
        qualified = self._ai_count(qualified_domain)

        avg_backlog_age = self._ai_average_age_days(not_called_domain)
        contact_rate = self._ai_rate(worked, generated)
        meeting_rate = self._ai_rate(meetings, generated)
        meeting_after_work_rate = self._ai_rate(meetings, worked)
        lost_rate = self._ai_rate(lost, generated)
        quality_rate = self._ai_rate(qualified, worked)

        return [
            self._ai_widget(
                "ai_generated",
                _("AI Leads Generated"),
                "kpi",
                generated,
                base_domain,
                "#2563eb",
                _("AI-sourced leads"),
                _("All CRM leads where Source is AI Generated."),
                value_format="integer",
                span=3,
            ),
            self._ai_widget(
                "ai_open",
                _("Open AI Leads"),
                "kpi",
                open_count,
                open_domain,
                "#0f766e",
                _("%s%% still active") % self._ai_rate(open_count, generated),
                _("AI leads that are still active/open."),
                value_format="integer",
                span=3,
            ),
            self._ai_widget(
                "ai_worked",
                _("Contact Rate"),
                "gauge",
                contact_rate,
                worked_domain,
                "#0891b2",
                _("%s worked / contacted") % worked,
                _("Share of AI leads with a call outcome captured."),
                value_format="percent",
                span=3,
            ),
            self._ai_widget(
                "ai_meetings",
                _("Meetings Set"),
                "kpi",
                meetings,
                meeting_domain,
                "#059669",
                _("%s%% of generated") % meeting_rate,
                _("Meeting outcome or meeting date captured."),
                value_format="integer",
                span=3,
            ),
            self._ai_widget(
                "ai_meeting_rate",
                _("Meeting Conversion"),
                "gauge",
                meeting_after_work_rate,
                meeting_domain,
                "#22c55e",
                _("%s%% once worked") % meeting_after_work_rate,
                _("Meetings set as a percentage of worked AI leads."),
                value_format="percent",
                span=3,
            ),
            self._ai_widget(
                "ai_quality_score",
                _("Lead Quality Rate"),
                "gauge",
                quality_rate,
                qualified_domain,
                "#2563eb",
                _("%s positive worked outcomes") % qualified,
                _("Worked leads that are meeting/follow-up/future-interest instead of unsuitable or unreachable."),
                value_format="percent",
                span=3,
            ),
            self._ai_widget(
                "ai_lost_rate",
                _("Lost / Archived Rate"),
                "gauge",
                lost_rate,
                lost_domain,
                "#dc2626",
                _("%s lost or archived") % lost,
                _("Includes AI leads marked lost and archived/lost leads hidden by default in CRM."),
                value_format="percent",
                span=3,
            ),
            self._ai_widget(
                "ai_backlog_age",
                _("Avg Backlog Age"),
                "kpi",
                avg_backlog_age,
                not_called_domain,
                "#f59e0b",
                _("days not yet called"),
                _("Average age of AI leads with no call outcome captured."),
                value_format="days",
                span=3,
            ),
            self._ai_widget(
                "ai_funnel",
                _("AI Lead Conversion Funnel"),
                "funnel",
                generated,
                base_domain,
                "#2563eb",
                _("Records"),
                _("Generated -> worked -> meetings -> qualified, with lost visible as leakage."),
                points=[
                    self._ai_point(_("Generated"), generated, base_domain),
                    self._ai_point(_("Worked"), worked, worked_domain),
                    self._ai_point(_("Meetings"), meetings, meeting_domain),
                    self._ai_point(_("Qualified Follow-up"), qualified, qualified_domain),
                    self._ai_point(_("Lost / Archived"), lost, lost_domain),
                ],
                groupby=_("Funnel Step"),
                value_format="integer",
                span=12,
            ),
            self._ai_widget(
                "ai_call_outcomes",
                _("Call Outcomes"),
                "column",
                worked,
                worked_domain,
                "#0891b2",
                _("Records"),
                _("Worked-lead outcomes grouped into execution buckets."),
                points=self._ai_call_outcome_points(worked_domain),
                groupby=_("Outcome Bucket"),
                value_format="integer",
                span=6,
            ),
            self._ai_widget(
                "ai_generated_by_week",
                _("Leads Generated by Week"),
                "column",
                generated,
                base_domain,
                "#2563eb",
                _("Records"),
                _("Weekly AI lead generation trend by ISO week number."),
                points=self._ai_week_points(base_domain, limit=12),
                groupby=_("Created Week"),
                value_format="integer",
                span=6,
            ),
            self._ai_widget(
                "ai_campaign_meeting_turnover",
                _("Campaign Meeting Turnover"),
                "bar",
                meetings,
                meeting_domain,
                "#059669",
                _("Meetings"),
                _("Campaigns ranked by meeting turnover, highest meeting count first."),
                points=self._ai_campaign_meeting_turnover_points(meeting_domain, limit=12),
                groupby=_("Campaign"),
                value_format="integer",
                span=6,
            ),
            self._ai_widget(
                "ai_salesperson_matrix",
                _("Salesperson Execution Matrix"),
                "matrix",
                generated,
                base_domain,
                "#0f766e",
                _("Records"),
                _("Owner-level contact, meeting, loss, and pipeline performance."),
                rows=self._ai_matrix_rows(base_domain, "user_id", limit=15),
                columns=[
                    {"key": "generated", "label": _("Generated"), "format": "integer"},
                    {"key": "worked_rate", "label": _("Worked %"), "format": "percent"},
                    {"key": "meetings", "label": _("Meetings"), "format": "integer"},
                    {"key": "meeting_rate", "label": _("Meeting %"), "format": "percent"},
                    {"key": "lost", "label": _("Lost"), "format": "integer"},
                    {"key": "pipeline", "label": _("Open Pipeline"), "format": "number"},
                ],
                groupby=_("Salesperson"),
                span=6,
            ),
        ]

    def _dashboard_crm_filter_options(self, date_from=False, date_to=False):
        self.ensure_one()
        if not self._is_ai_generated_leads_dashboard() or "crm.lead" not in self.env:
            return {"enabled": False}
        base_domain = self._ai_base_domain(date_from=date_from, date_to=date_to)
        return {
            "enabled": True,
            "campaigns": self._crm_filter_options_for_field(base_domain, "campaign_id"),
            "salespeople": self._crm_filter_options_for_field(base_domain, "user_id"),
            "teams": self._crm_filter_options_for_field(base_domain, "team_id"),
            "stages": self._crm_filter_options_for_field(base_domain, "stage_id"),
        }

    def _crm_filter_options_for_field(self, domain, field_name):
        rows = self._ai_lead_model().read_group(
            domain,
            [field_name],
            [field_name],
            lazy=False,
            limit=80,
        )
        options = []
        for row in rows:
            value = row.get(field_name)
            if not value:
                continue
            options.append({"id": value[0], "name": value[1], "count": row.get("__count", 0)})
        return sorted(options, key=lambda option: option["name"])

    def _json_safe(self, value):
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        return value

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
            "views": [
                [False, "list"],
                [False, "form"],
                [False, "pivot"],
                [False, "graph"],
            ],
            "domain": parsed_domain,
            "context": {"active_test": False} if model_name == "crm.lead" else {},
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
