from datetime import timedelta

from odoo import fields, models, _

OPS_DASHBOARD_NAME = "Ops Performance"

# How many past weeks to offer in the week selector.
WEEK_OPTIONS_COUNT = 26


class LinkederpDashboardOps(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_ops_dashboard()

    def _ensure_ops_dashboard(self):
        if self.search([("name", "=", OPS_DASHBOARD_NAME)], limit=1):
            return
        if "account.analytic.line" not in self.env:
            return
        self.create(
            {
                "name": OPS_DASHBOARD_NAME,
                "sequence": 30,
                "description": _(
                    "Weekly operations review. Select a week to review the team's "
                    "time-entry discipline and delivery."
                ),
                "color": "#1d4ed8",
            }
        )

    def _is_ops_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == OPS_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Week selector
    # ------------------------------------------------------------------
    def _ops_week_start(self, day):
        return day - timedelta(days=day.weekday())

    def _ops_last_completed_week(self):
        today = fields.Date.context_today(self)
        return self._ops_week_start(today) - timedelta(days=7)

    def _ops_week_label(self, week_start):
        week_end = week_start + timedelta(days=6)
        return "W%02d · %s – %s" % (
            week_start.isocalendar()[1],
            week_start.strftime("%d %b"),
            week_end.strftime("%d %b %Y"),
        )

    def _ops_selected_week(self, filters=False):
        filters = filters or {}
        value = filters.get("week")
        if value:
            selected = fields.Date.to_date(value)
            if selected:
                return self._ops_week_start(selected)
        return self._ops_last_completed_week()

    def _ops_week_options(self):
        last = self._ops_last_completed_week()
        weeks = [last - timedelta(days=7 * i) for i in range(WEEK_OPTIONS_COUNT)]
        return [
            {"value": fields.Date.to_string(ws), "label": self._ops_week_label(ws)}
            for ws in weeks
        ]

    def _ops_filter_options(self, filters=False):
        return {
            "enabled": True,
            "weeks": self._ops_week_options(),
            "selected": fields.Date.to_string(self._ops_selected_week(filters)),
        }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def _ops_timesheet_week_domain(self, week_start):
        week_end = week_start + timedelta(days=6)
        return [
            ("project_id", "!=", False),
            ("date", ">=", fields.Date.to_string(week_start)),
            ("date", "<=", fields.Date.to_string(week_end)),
        ]

    def _ops_pass_rate(self, week_start):
        """Return (rate, on_time, total, cutoff_date).

        Pass = a project timesheet line dated in the reviewed week whose
        Created-on date is on/before the Monday of the following week.
        Counted across all companies.
        """
        cutoff = week_start + timedelta(days=7)  # Monday of the following week
        base = self._ops_timesheet_week_domain(week_start)
        Line = self.env["account.analytic.line"].with_context(active_test=False)
        total = Line.search_count(base)
        on_time = Line.search_count(
            base + [("create_date", "<=", "%s 23:59:59" % fields.Date.to_string(cutoff))]
        )
        rate = round(on_time / total * 100, 1) if total else 0.0
        return rate, on_time, total, cutoff

    def _ops_pass_rate_color(self, rate):
        if rate >= 100:
            return "#2e7d2e"
        if rate >= 90:
            return "#c98a1b"
        return "#b03030"

    def _ops_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        week_start = self._ops_selected_week(filters)
        rate, on_time, total, cutoff = self._ops_pass_rate(week_start)

        pass_card = {
            "id": "ops_pass_rate",
            "name": _("Time Entry Pass Rate"),
            "type": "kpi",
            "model": "account.analytic.line",
            "mode": "computed",
            "measure": _("%(on)s / %(total)s lines entered on time") % {
                "on": on_time,
                "total": total,
            },
            "groupby": "",
            "color": self._ops_pass_rate_color(rate),
            "help": _("Reviewed %(week)s · on time = created on/before %(cutoff)s") % {
                "week": self._ops_week_label(week_start),
                "cutoff": cutoff.strftime("%d %b %Y"),
            },
            "value": float(rate),
            "format": "percent",
            "domain": self._json_safe(self._ops_timesheet_week_domain(week_start)),
            "points": [],
            "rows": [],
            "columns": [],
            "span": 3,
            "error": False,
        }
        return [pass_card]
