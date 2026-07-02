import logging
from datetime import date, timedelta

from odoo import fields, models, _

from .ops_dashboard import BILLABLE_SHARE, OPS_SUBTEAM_FIELD

_logger = logging.getLogger(__name__)

OPS_WEEKLY_DASHBOARD_NAME = "Ops Weekly Teams"

# % Fail tones: green below 10, amber 10-20, red at/above 20.
FAIL_GREEN_BELOW = 10.0
FAIL_RED_FROM = 20.0

# Billability target: dotted line on the bar chart, green/red split.
WEEKLY_BILL_TARGET = 75.0

# Label every trend point up to this many points; above it, every 2nd.
TREND_LABEL_MAX_POINTS = 32


class LinkederpDashboardOpsWeekly(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_weekly_dashboard()

    def _ensure_weekly_dashboard(self):
        if self.search([("name", "=", OPS_WEEKLY_DASHBOARD_NAME)], limit=1):
            return
        if "account.analytic.line" not in self.env:
            return
        self.create(
            {
                "name": OPS_WEEKLY_DASHBOARD_NAME,
                "sequence": 50,
                "description": _(
                    "Weekly team view: time-entry failures and billability, year "
                    "to date. Click a week on the trend chart to focus the page."
                ),
                "color": "#1d4ed8",
            }
        )

    def _is_weekly_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == OPS_WEEKLY_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Scope (Year to date, or one clicked week)
    # ------------------------------------------------------------------
    def _weekly_ytd_weeks(self):
        """ISO weeks W01 (of the last completed week's ISO year) .. last completed."""
        last = self._ops_last_completed_week()
        first = date.fromisocalendar(last.isocalendar()[0], 1, 1)
        weeks = []
        week = first
        while week <= last:
            weeks.append(week)
            week += timedelta(days=7)
        return weeks

    def _weekly_selected_week(self, filters=False):
        """Monday of the clicked week, or False for Year to date."""
        filters = filters or {}
        value = filters.get("team_week")
        if value:
            selected = fields.Date.to_date(value)
            if selected:
                week = self._ops_week_start(selected)
                if week in self._weekly_ytd_weeks():
                    return week
        return False

    def _weekly_scope_label(self, week):
        return self._ops_week_label(week) if week else _("Year to date")

    def _weekly_filter_options(self, filters=False):
        week = self._weekly_selected_week(filters)
        return {
            "enabled": True,
            "selected": fields.Date.to_string(week) if week else "",
            "selected_label": self._weekly_scope_label(week),
        }
