import ast
from datetime import date, datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.osv import expression

DASHBOARD_BUCKETS = [
    ("sales", "Sales"),
    ("ops", "Ops"),
    ("finance", "Finance"),
    ("hr", "HR"),
    ("management", "Management"),
]

BUCKET_GROUP_XMLIDS = {
    "sales": "linkederp_dashboard_studio.group_dashboard_bucket_sales",
    "ops": "linkederp_dashboard_studio.group_dashboard_bucket_ops",
    "finance": "linkederp_dashboard_studio.group_dashboard_bucket_finance",
    "hr": "linkederp_dashboard_studio.group_dashboard_bucket_hr",
    "management": "linkederp_dashboard_studio.group_dashboard_bucket_management",
}

MANAGER_GROUP_XMLID = "linkederp_dashboard_studio.group_dashboard_studio_manager"

# Renamed 2026-07-03 per Akshay; legacy names kept as aliases so records
# created under the old names still map to their buckets.
AI_DASHBOARD_NAME = "Nighthawk Review Dashboard"
AI_DASHBOARD_LEGACY = "AI Generated Leads Performance"

# x_studio_call_outcome selection values the Nighthawk engine reasons about.
AI_QUALIFIED_OUTCOMES = ["Meeting Set", "Send more Info", "Call Later", "Future Interest"]
AI_ALL_OUTCOMES = AI_QUALIFIED_OUTCOMES + [
    "Contact Not a Fit", "Company Not a fit", "Unable to make Contact"]
# Positive outcomes still in play but NOT yet a meeting (funnel stage r2:
# keeps the funnel free of the Meetings double-count Akshay spotted).
AI_FOLLOWUP_OUTCOMES = [o for o in AI_QUALIFIED_OUTCOMES if o != "Meeting Set"]

DEFAULT_BUCKET_BY_NAME = {
    "Sales & CRM Dashboard": "sales",
    "Sales Performance Dashboard": "management",
    "Aurika Sales Dashboard": "management",
    "Nighthawk Review Dashboard": "sales",
    "AI Generated Leads Performance": "sales",
    "Ops Weekly review": "ops",
    "Ops Performance": "ops",
    "Ops Monthly Awards": "management",
    "Weekly Chain Update": "management",
    "Ops Weekly Teams": "management",
    "Aurika Ops Dashboard": "management",
    "Ops Management": "management",
    "Weekly Support & SLA Dashboard": "ops",
    "Aurika Finance Dashboard": "management",
    "Aurika People Dashboard": "management",
    "Odoo Partnership Tier": "management",
}


class LinkederpDashboard(models.Model):
    _name = "linkederp.dashboard"
    _description = "LinkedERP Dashboard"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    color = fields.Char(default="#2563eb")
    bucket = fields.Selection(
        DASHBOARD_BUCKETS,
        string="Bucket",
        help="Section of the dashboard selector this dashboard appears in. "
        "Access is granted through the bucket's security group.",
    )
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
        help="Extra groups that can also see this dashboard, in addition to "
        "its bucket's security group and Dashboard Managers.",
    )
    widget_ids = fields.One2many(
        "linkederp.dashboard.widget",
        "dashboard_id",
        string="Widgets",
        copy=True,
    )

    def _visible_to_current_user(self):
        if self.env.su or self.env.user.has_group(MANAGER_GROUP_XMLID):
            return self
        user_groups = self._current_user_groups()
        bucket_groups = self._bucket_groups()

        def visible(dashboard):
            bucket_group = bucket_groups.get(dashboard.bucket)
            if bucket_group and bucket_group in user_groups:
                return True
            return bool(dashboard.allowed_group_ids & user_groups)

        return self.filtered(visible)

    @api.model
    def _bucket_groups(self):
        groups = {}
        for key, xmlid in BUCKET_GROUP_XMLIDS.items():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups[key] = group
        return groups

    def _current_user_groups(self):
        user = self.env.user
        # Prefer the implied-groups closure (Odoo 19) so memberships granted
        # via group inheritance count as well.
        if "all_group_ids" in user._fields:
            return user.all_group_ids
        if "groups_id" in user._fields:
            return user.groups_id
        if "group_ids" in user._fields:
            return user.group_ids
        return self.env["res.groups"]

    @api.model
    def get_dashboard_payload(self, dashboard_id=False, date_from=False, date_to=False, filters=False):
        self.sudo()._ensure_packaged_dashboards()
        self.sudo()._assign_default_buckets()
        dashboards = self.search([("active", "=", True)], order="sequence, name")
        dashboards = dashboards._visible_to_current_user()

        if dashboard_id:
            dashboard = self.browse(int(dashboard_id)).exists()
            if not dashboard or dashboard.id not in dashboards.ids:
                # Stale saved selection, archived dashboard, or revoked
                # access: fall back to the first visible dashboard instead
                # of failing the whole page.
                dashboard = dashboards[:1]
        else:
            dashboard = dashboards[:1]

        # Visibility was checked above as the real user; the numbers are
        # computed with elevated rights so every allowed viewer sees the
        # same figures regardless of their own record rules.
        dashboard = dashboard.sudo()

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
            elif dashboard._is_ops_dashboard():
                widgets = dashboard._ops_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_awards_dashboard():
                widgets = dashboard._awards_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_weekly_dashboard():
                widgets = dashboard._weekly_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_mgmt_dashboard():
                widgets = dashboard._mgmt_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_sales_dashboard():
                widgets = dashboard._sales_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_sla_dashboard():
                widgets = dashboard._sla_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_finance_dashboard():
                widgets = dashboard._finance_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_people_dashboard():
                widgets = dashboard._people_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )
            elif dashboard._is_tier_dashboard():
                widgets = dashboard._tier_dashboard_widgets(
                    date_from=date_from,
                    date_to=date_to,
                    filters=filters,
                )

        bucket_labels = dict(DASHBOARD_BUCKETS)
        return {
            "dashboards": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description or "",
                    "color": item.color or "#2563eb",
                    "bucket": item.bucket or "management",
                    "bucket_label": bucket_labels.get(
                        item.bucket or "management", _("Management")
                    ),
                }
                for item in dashboards
            ],
            "bucket_order": [
                {"key": key, "label": label} for key, label in DASHBOARD_BUCKETS
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
            "ops_filters": dashboard._ops_filter_options(filters)
            if dashboard and dashboard._is_ops_dashboard()
            else {"enabled": False},
            "awards_filters": dashboard._awards_filter_options(filters)
            if dashboard and dashboard._is_awards_dashboard()
            else {"enabled": False},
            "weekly_filters": dashboard._weekly_filter_options(filters)
            if dashboard and dashboard._is_weekly_dashboard()
            else {"enabled": False},
            "mgmt_filters": dashboard._mgmt_filter_options(filters)
            if dashboard and dashboard._is_mgmt_dashboard()
            else {"enabled": False},
            "sales_filters": dashboard._sales_filter_options(filters)
            if dashboard and dashboard._is_sales_dashboard()
            else {"enabled": False},
            "sla_filters": dashboard._sla_filter_options(filters)
            if dashboard and dashboard._is_sla_dashboard()
            else {"enabled": False},
            "fin_filters": dashboard._fin_filter_options(filters)
            if dashboard and dashboard._is_finance_dashboard()
            else {"enabled": False},
            "people_filters": dashboard._people_filter_options(filters)
            if dashboard and dashboard._is_people_dashboard()
            else {"enabled": False},
        }

    @api.model
    def _ensure_packaged_dashboards(self):
        self._ensure_default_sales_crm_dashboard()
        self._ensure_ai_generated_leads_dashboard()

    @api.model
    def _ensure_dashboard_name(self, name, legacy_names):
        """True when the packaged dashboard already exists — renaming a
        legacy-named record in place if needed (2026-07-03 renames); False
        when the caller must create it."""
        Dash = self.with_context(active_test=False)
        if Dash.search([("name", "=", name)], limit=1):
            return True
        for legacy in legacy_names:
            record = Dash.search([("name", "=", legacy)], limit=1)
            if record:
                record.write({"name": name})
                return True
        return False

    @api.model
    def _assign_default_buckets(self):
        """One-time backfill: any dashboard without a bucket gets one by name.

        The Sales & CRM starter is archived the first (and only) time it
        receives its bucket, so un-archiving it later sticks.
        """
        unassigned = self.with_context(active_test=False).search(
            [("bucket", "=", False)]
        )
        for dashboard in unassigned:
            vals = {"bucket": DEFAULT_BUCKET_BY_NAME.get(dashboard.name, "management")}
            if dashboard.name == "Sales & CRM Dashboard" and dashboard.active:
                vals["active"] = False
            dashboard.write(vals)

    @api.model
    def _ensure_default_sales_crm_dashboard(self):
        if self.with_context(active_test=False).search([("name", "=", "Sales & CRM Dashboard")], limit=1):
            return
        if "sale.order" not in self.env or "crm.lead" not in self.env:
            return

        dashboard = self.create(
            {
                "name": _("Sales & CRM Dashboard"),
                "sequence": 10,
                "bucket": "sales",
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
        if self._ensure_dashboard_name(AI_DASHBOARD_NAME, [AI_DASHBOARD_LEGACY]):
            return
        if "crm.lead" not in self.env:
            return
        self.create(
            {
                "name": AI_DASHBOARD_NAME,
                "sequence": 20,
                "bucket": "sales",
                "description": _(
                    "Track AI-sourced CRM lead volume, calling work, meetings, suitability, ownership, and pipeline movement."
                ),
                "color": "#0f766e",
            }
        )

    def _is_ai_generated_leads_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() in (
            AI_DASHBOARD_NAME.lower(), AI_DASHBOARD_LEGACY.lower())

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
        info="",
        modal_table=False,
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
            "info": info,
            "modal_table": modal_table,
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
            not_called_domain = expression.AND([group_domain, [("x_studio_call_outcome", "=", False)]])
            open_domain = expression.AND([group_domain, [("active", "=", True)]])
            worked = self._ai_count(worked_domain)
            open_count = self._ai_count(open_domain)
            meetings = self._ai_count(meeting_domain)
            lost = self._ai_count(lost_domain)
            rows.append(
                {
                    "label": group["label"],
                    "domain": self._json_safe(group_domain),
                    "generated": generated,
                    "worked": worked,
                    "open": open_count,
                    "meetings": meetings,
                    "meeting_rate": self._ai_rate(meetings, generated),
                    "lost": lost,
                    "ageing": self._ai_average_age_days(not_called_domain),
                }
            )
        return sorted(rows, key=lambda row: (row["meeting_rate"], row["meetings"], row["generated"]), reverse=True)

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

    def _ai_campaign_conversion_rows(self, base_domain, limit=12):
        groups = self._ai_group_points(base_domain, "campaign_id", limit=limit)
        rows = []
        meeting_extra_domain = [
            "|",
            ("x_studio_call_outcome", "=", "Meeting Set"),
            ("x_studio_meeting_date", "!=", False),
        ]
        for group in groups:
            group_domain = group["domain"]
            meeting_domain = expression.AND([group_domain, meeting_extra_domain])
            generated = self._ai_count(group_domain)
            meetings = self._ai_count(meeting_domain)
            rows.append(
                {
                    "label": group["label"],
                    "domain": self._json_safe(group_domain),
                    "generated": generated,
                    "meetings": meetings,
                    "meeting_rate": self._ai_rate(meetings, generated),
                    "meetings_domain": self._json_safe(meeting_domain),
                }
            )
        return sorted(rows, key=lambda row: (row["meetings"], row["meeting_rate"], row["generated"]), reverse=True)

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

    def _ai_modal(self, name, color, groupby, rows, share_label, help_text=""):
        """modal_table dict for the shared MatrixTable popup; rows drill."""
        return {
            "name": name,
            "help": help_text,
            "color": color,
            "groupby": groupby,
            "compact": True,
            "columns": [
                {"key": "count", "label": _("Leads"), "format": "integer"},
                {"key": "share", "label": share_label, "format": "percent"},
            ],
            "rows": rows,
        }

    def _ai_modal_row(self, label, count, total, domain, seen_labels):
        # MatrixTable t-keys off row.label: suffix duplicates (learning #13).
        base = label or _("Undefined")
        label = base
        serial = 2
        while label in seen_labels:
            label = "%s (%s)" % (base, serial)
            serial += 1
        seen_labels.add(label)
        return {
            "label": label,
            "count": count,
            "share": self._ai_rate(count, total),
            "model": "crm.lead",
            "domain": self._json_safe(domain),
        }

    def _ai_outcome_breakdown_rows(self, base_domain, outcomes, total, include_other=False):
        """One popup row per call-outcome value inside base_domain."""
        rows = []
        seen = set()
        for outcome in outcomes:
            domain = expression.AND([base_domain, [("x_studio_call_outcome", "=", outcome)]])
            count = self._ai_count(domain)
            rows.append(self._ai_modal_row(outcome, count, total, domain, seen))
        if include_other:
            other_domain = expression.AND(
                [base_domain, [("x_studio_call_outcome", "not in", outcomes)]]
            )
            other = self._ai_count(other_domain)
            if other:
                rows.append(self._ai_modal_row(_("Other outcomes"), other, total, other_domain, seen))
        rows.sort(key=lambda row: row["count"], reverse=True)
        return rows

    def _ai_lost_reason_rows(self, lost_domain, total):
        """One popup row per lost reason (plus 'No reason set')."""
        grouped = self._ai_lead_model().read_group(
            lost_domain, ["lost_reason_id"], ["lost_reason_id"], lazy=False
        )
        data = []
        for row in grouped:
            value = row.get("lost_reason_id")
            label = value[1] if value else _("No reason set")
            data.append((label, row.get("__count", 0), row.get("__domain", lost_domain)))
        data.sort(key=lambda item: item[1], reverse=True)
        seen = set()
        return [
            self._ai_modal_row(label, count, total, domain, seen)
            for label, count, domain in data
        ]

    def _ai_backlog_age_rows(self, not_called_domain, total):
        """Ageing buckets (days since creation) over the un-called backlog."""
        today = fields.Date.context_today(self)

        def day_floor(days_ago):
            return "%s 00:00:00" % fields.Date.to_string(today - timedelta(days=days_ago))

        buckets = [
            (_("Over 30 days"), [("create_date", "<", day_floor(30))]),
            (_("16–30 days"), [("create_date", ">=", day_floor(30)),
                               ("create_date", "<", day_floor(15))]),
            (_("11–15 days"), [("create_date", ">=", day_floor(15)),
                               ("create_date", "<", day_floor(10))]),
            (_("6–10 days"), [("create_date", ">=", day_floor(10)),
                              ("create_date", "<", day_floor(5))]),
            (_("3–5 days"), [("create_date", ">=", day_floor(5)),
                             ("create_date", "<", day_floor(2))]),
            (_("0–2 days"), [("create_date", ">=", day_floor(2))]),
        ]
        rows = []
        seen = set()
        for label, extra in buckets:
            domain = expression.AND([not_called_domain, extra])
            rows.append(self._ai_modal_row(label, self._ai_count(domain), total, domain, seen))
        rows.append(self._ai_modal_row(_("Total backlog"), total, total, not_called_domain, seen))
        return rows

    def _ai_trend_modal(self, name, color, base_domain, extra_domain, help_text):
        """4-week popup bar chart: leads CREATED each ISO week matching
        extra_domain. Fixed horizon (page date filter doesn't move it);
        campaign/rep/team/stage filters flow in via base_domain.
        ponytail: cohort-by-creation-week until outcome tracking (ON since
        2026-07-14) accumulates enough history for true activity weeks."""
        today = fields.Date.context_today(self)
        monday = today - timedelta(days=today.weekday())
        points = []
        for back in range(3, -1, -1):
            week_start = monday - timedelta(days=7 * back)
            week_end = week_start + timedelta(days=6)
            domains = [base_domain, [
                ("create_date", ">=", "%s 00:00:00" % fields.Date.to_string(week_start)),
                ("create_date", "<=", "%s 23:59:59" % fields.Date.to_string(week_end)),
            ]]
            if extra_domain:
                domains.append(extra_domain)
            domain = expression.AND(domains)
            points.append(self._ai_point(
                _("Wk %s") % ("%02d" % week_start.isocalendar()[1]),
                self._ai_count(domain), domain))
        return {
            "name": name,
            "help": help_text,
            "color": color,
            "model": "crm.lead",
            "format": "integer",
            "points": points,
        }

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
            extra_domain=[("x_studio_call_outcome", "in", AI_QUALIFIED_OUTCOMES)],
        )
        qualified = self._ai_count(qualified_domain)

        # Funnel stage r2 (2026-07-14): positive outcomes NOT yet at meeting
        # stage — disjoint from the Meetings stage by construction, so the
        # same lead can never show in both bars (Akshay's double-count spot).
        follow_up_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[
                ("x_studio_call_outcome", "in", AI_FOLLOWUP_OUTCOMES),
                ("x_studio_meeting_date", "=", False),
            ],
        )
        follow_up = self._ai_count(follow_up_domain)

        # Actionable calling backlog: OPEN leads never worked. Deliberately
        # narrower than not_called_domain (which also carries archived
        # never-called leads and stays the Avg Backlog Age population).
        not_worked_open_domain = self._ai_base_domain(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            extra_domain=[("active", "=", True), ("x_studio_call_outcome", "=", False)],
        )
        not_worked_open = self._ai_count(not_worked_open_domain)

        avg_backlog_age = self._ai_average_age_days(not_called_domain)
        contact_rate = self._ai_rate(worked, generated)
        meeting_rate = self._ai_rate(meetings, generated)
        meeting_after_work_rate = self._ai_rate(meetings, worked)
        lost_rate = self._ai_rate(lost, generated)
        quality_rate = self._ai_rate(qualified, worked)

        quality_modal = self._ai_modal(
            _("Lead Quality Rate — by call outcome"),
            "#2563eb",
            _("Call Outcome"),
            self._ai_outcome_breakdown_rows(qualified_domain, AI_QUALIFIED_OUTCOMES, qualified),
            _("% of qualified"),
            _("Positive worked outcomes; click a row for those leads."),
        )
        lost_modal = self._ai_modal(
            _("Lost / Archived — by lost reason"),
            "#dc2626",
            _("Lost Reason"),
            self._ai_lost_reason_rows(lost_domain, lost),
            _("% of lost"),
            _("Lost and archived AI leads; click a row for those leads."),
        )
        backlog_modal = self._ai_modal(
            _("Backlog ageing — days since creation"),
            "#f59e0b",
            _("Age Bucket"),
            self._ai_backlog_age_rows(not_called_domain, not_called),
            _("% of backlog"),
            _("AI leads with no call outcome yet; click a row for those leads."),
        )
        worked_modal = self._ai_modal(
            _("Worked — by call outcome"),
            "#0891b2",
            _("Call Outcome"),
            self._ai_outcome_breakdown_rows(worked_domain, AI_ALL_OUTCOMES, worked, include_other=True),
            _("% of worked"),
            _("Every worked AI lead by its recorded call outcome."),
        )
        follow_up_modal = self._ai_modal(
            _("Follow-up in Progress — by call outcome"),
            "#7c3aed",
            _("Call Outcome"),
            self._ai_outcome_breakdown_rows(follow_up_domain, AI_FOLLOWUP_OUTCOMES, follow_up),
            _("% of follow-ups"),
            _("Positive outcomes still being chased — no meeting yet."),
        )
        trend_base = self._ai_base_domain(filters=filters)
        contact_trend_modal = self._ai_trend_modal(
            _("Contact trend — last 4 weeks"),
            "#0891b2",
            trend_base,
            [("x_studio_call_outcome", "!=", False)],
            _("Leads from each week that have been called so far. The rep/"
              "campaign filters above apply; the date range does not move "
              "this view. Click a bar for those leads."),
        )
        meetings_trend_modal = self._ai_trend_modal(
            _("Meetings trend — last 4 weeks"),
            "#059669",
            trend_base,
            ["|", ("x_studio_call_outcome", "=", "Meeting Set"),
             ("x_studio_meeting_date", "!=", False)],
            _("Meetings from each week's leads. The rep/campaign filters "
              "above apply; the date range does not move this view. Click "
              "a bar for those leads."),
        )

        return [
            self._ai_widget(
                "ai_generated",
                _("AI Leads Generated"),
                "kpi",
                generated,
                base_domain,
                "#2563eb",
                _("AI-sourced leads"),
                value_format="integer",
                span=3,
                info=_(
                    "Definition: every CRM lead whose Source is 'AI Generated', "
                    "created in the selected date range. "
                    "Calculation: simple count of those leads."
                ),
            ),
            self._ai_widget(
                "ai_open",
                _("Open AI Leads"),
                "kpi",
                open_count,
                open_domain,
                "#0f766e",
                _("%s%% still active") % self._ai_rate(open_count, generated),
                value_format="integer",
                span=3,
                info=_(
                    "Definition: generated AI leads that are still open (not "
                    "lost or archived). "
                    "Calculation: count of active AI leads; the caption shows "
                    "active ÷ generated."
                ),
            ),
            self._ai_widget(
                "ai_worked",
                _("Contact Rate"),
                "gauge",
                contact_rate,
                worked_domain,
                "#0891b2",
                _("%s worked / contacted") % worked,
                value_format="percent",
                span=3,
                info=_(
                    "Definition: share of AI leads the team has actually "
                    "worked. "
                    "Calculation: leads with any Call Outcome marked ÷ all AI "
                    "leads in range × 100. Click for the 4-week contact "
                    "trend (respects the rep filter)."
                ),
                modal_table=contact_trend_modal,
            ),
            self._ai_widget(
                "ai_meetings",
                _("Meetings Set"),
                "kpi",
                meetings,
                meeting_domain,
                "#059669",
                _("%(gen)s%% of generated · %(worked)s%% once worked")
                % {"gen": meeting_rate, "worked": meeting_after_work_rate},
                value_format="integer",
                span=3,
                info=_(
                    "Definition: leads where the call ended in 'Meeting Set' "
                    "or a meeting date is filled. "
                    "Calculation: count of such leads; '% of generated' = "
                    "meetings ÷ all AI leads; '% once worked' = meetings ÷ "
                    "worked leads (the old Meeting Conversion card, now "
                    "merged here). Click for the 4-week meetings trend "
                    "(respects the rep filter)."
                ),
                modal_table=meetings_trend_modal,
            ),
            self._ai_widget(
                "ai_not_worked",
                _("Not Yet Worked"),
                "kpi",
                not_worked_open,
                not_worked_open_domain,
                "#d97706",
                _("%s%% of generated · open, no call outcome")
                % self._ai_rate(not_worked_open, generated),
                value_format="integer",
                span=3,
                info=_(
                    "Definition: the calling backlog — open AI leads where "
                    "Call Outcome is still empty. "
                    "Calculation: count of active AI leads with no Call "
                    "Outcome; archived never-called leads are excluded. "
                    "Click to open the leads and start working them."
                ),
            ),
            self._ai_widget(
                "ai_quality_score",
                _("Lead Quality Rate"),
                "gauge",
                quality_rate,
                qualified_domain,
                "#2563eb",
                _("%s positive worked outcomes") % qualified,
                value_format="percent",
                span=3,
                info=_(
                    "Definition: of the worked leads, the share with a "
                    "positive outcome (Meeting Set, Send more Info, Call "
                    "Later, Future Interest). "
                    "Calculation: positive-outcome leads ÷ worked leads × "
                    "100. Click the dial for the count by outcome."
                ),
                modal_table=quality_modal,
            ),
            self._ai_widget(
                "ai_lost_rate",
                _("Lost / Archived Rate"),
                "gauge",
                lost_rate,
                lost_domain,
                "#dc2626",
                _("%s lost or archived") % lost,
                value_format="percent",
                span=3,
                info=_(
                    "Definition: AI leads marked Lost, plus archived leads "
                    "(hidden by default in CRM). "
                    "Calculation: lost-or-archived ÷ all AI leads × 100. "
                    "Click the dial for the count by lost reason."
                ),
                modal_table=lost_modal,
            ),
            self._ai_widget(
                "ai_backlog_age",
                _("Avg Backlog Age"),
                "kpi",
                avg_backlog_age,
                not_called_domain,
                "#f59e0b",
                _("days not yet called"),
                value_format="days",
                span=3,
                info=_(
                    "Definition: average age (days since creation) of AI "
                    "leads with no call outcome yet. "
                    "Calculation: mean of (today − created date) across that "
                    "backlog. Click for the ageing buckets (0–2, 3–5, 6–10, "
                    "11–15, 16–30, over 30 days)."
                ),
                modal_table=backlog_modal,
            ),
            self._ai_widget(
                "ai_funnel",
                _("AI Lead Conversion Funnel"),
                "funnel",
                generated,
                base_domain,
                "#2563eb",
                _("Records"),
                points=[
                    self._ai_point(_("Generated"), generated, base_domain),
                    dict(
                        self._ai_point(_("Worked"), worked, worked_domain),
                        modal_table=worked_modal,
                    ),
                    dict(
                        self._ai_point(_("Follow-up in Progress"), follow_up, follow_up_domain),
                        modal_table=follow_up_modal,
                    ),
                    self._ai_point(_("Meetings"), meetings, meeting_domain),
                    dict(
                        self._ai_point(_("Lost / Archived"), lost, lost_domain),
                        modal_table=lost_modal,
                    ),
                ],
                groupby=_("Funnel Step"),
                value_format="integer",
                span=12,
                info=_(
                    "Definition: how AI leads move through the pipeline. "
                    "Generated = all AI leads; Worked = call outcome marked; "
                    "Follow-up in Progress = positive outcomes still being "
                    "chased (Call Later, Send more Info, Future Interest) "
                    "with NO meeting yet; Meetings = meeting set or meeting "
                    "date; Lost / Archived = leakage. A lead appears in only "
                    "ONE of Follow-up and Meetings — never both. Click "
                    "Worked or Follow-up for the call-outcome breakdown, "
                    "Lost for the lost-reason breakdown."
                ),
            ),
            self._ai_widget(
                "ai_call_outcomes",
                _("Call Outcomes"),
                "column",
                worked,
                worked_domain,
                "#0891b2",
                _("Records"),
                points=self._ai_call_outcome_points(worked_domain),
                groupby=_("Outcome Bucket"),
                value_format="integer",
                span=6,
                info=_(
                    "Definition: worked leads grouped by result — Meeting "
                    "Set; In Progress (Call Later, Send more Info, Future "
                    "Interest); Not Suitable (contact or company not a fit); "
                    "Unreachable. Calculation: count of worked leads per "
                    "bucket; click a bar for those leads."
                ),
            ),
            self._ai_widget(
                "ai_generated_by_week",
                _("Leads Generated by Week"),
                "column",
                generated,
                base_domain,
                "#2563eb",
                _("Records"),
                points=self._ai_week_points(base_domain, limit=12),
                groupby=_("Created Week"),
                value_format="integer",
                span=6,
                info=_(
                    "Definition: new AI leads per ISO calendar week (by "
                    "created date). Calculation: count of leads created in "
                    "each week; last 12 weeks with data are shown."
                ),
            ),
            self._ai_widget(
                "ai_campaign_conversion",
                _("Campaign Leads vs Meetings"),
                "comparison",
                generated,
                base_domain,
                "#059669",
                _("Leads / Meetings"),
                rows=self._ai_campaign_conversion_rows(base_domain, limit=12),
                groupby=_("Campaign"),
                value_format="integer",
                span=6,
                info=_(
                    "Definition: per campaign, generated AI leads compared "
                    "with meetings set from them. Calculation: meetings = "
                    "leads with 'Meeting Set' outcome or a meeting date; "
                    "conversion = meetings ÷ generated per campaign."
                ),
            ),
            self._ai_widget(
                "ai_salesperson_matrix",
                _("Salesperson Execution Matrix"),
                "matrix",
                generated,
                base_domain,
                "#0f766e",
                _("Records"),
                info=_(
                    "Definition: per lead owner — Generated (all AI leads), "
                    "Worked (call outcome marked), Open (still active), "
                    "Meetings Set (+% of generated), Lost, and Ageing = "
                    "average days the owner's un-called leads have waited. "
                    "Calculation: counts within the selected date range and "
                    "filters; click a row for that person's leads."
                ),
                rows=self._ai_matrix_rows(base_domain, "user_id", limit=15),
                columns=[
                    {"key": "generated", "label": _("Generated"), "format": "integer"},
                    {"key": "worked", "label": _("Worked"), "format": "integer"},
                    {"key": "open", "label": _("Open"), "format": "integer"},
                    {"key": "meetings", "label": _("Meetings Set"), "format": "integer"},
                    {"key": "meeting_rate", "label": _("Meetings %"), "format": "percent"},
                    {"key": "lost", "label": _("Lost"), "format": "integer"},
                    {"key": "ageing", "label": _("Ageing"), "format": "days"},
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
            # crm.lead hides lost leads and hr.employee hides departed staff
            # by default; drill-downs of those (e.g. leavers) must show them.
            "context": {"active_test": False}
            if model_name in ("crm.lead", "hr.employee") else {},
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
