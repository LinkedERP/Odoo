import logging
from datetime import date, timedelta

from odoo import fields, models, _

from .ops_dashboard import BILLABLE_SHARE, OPS_SUBTEAM_FIELD

_logger = logging.getLogger(__name__)

OPS_AWARDS_DASHBOARD_NAME = "Ops Monthly Awards"

# How many past months to offer in the month selector.
MONTH_OPTIONS_COUNT = 12

# An employee must be eligible for at least this many of the month's weeks to
# appear in the employee standings.
AWARDS_MIN_ELIGIBLE_WEEKS = 2

# How many employees the standings table shows.
AWARDS_EMPLOYEE_TOP_N = 5


class LinkederpDashboardOpsAwards(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_awards_dashboard()

    def _ensure_awards_dashboard(self):
        if self.search([("name", "=", OPS_AWARDS_DASHBOARD_NAME)], limit=1):
            return
        if "account.analytic.line" not in self.env:
            return
        self.create(
            {
                "name": OPS_AWARDS_DASHBOARD_NAME,
                "sequence": 40,
                "description": _(
                    "Monthly operations awards. Pick a month to crown the champion "
                    "team and employee on billability and time-entry discipline."
                ),
                "color": "#1d4ed8",
            }
        )

    def _is_awards_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == OPS_AWARDS_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Month selector
    # ------------------------------------------------------------------
    def _awards_prev_month(self, month_first):
        if month_first.month == 1:
            return date(month_first.year - 1, 12, 1)
        return date(month_first.year, month_first.month - 1, 1)

    def _awards_month_weeks(self, month_first):
        """Mondays of the ISO weeks belonging to this month (Monday inside it)."""
        day = month_first + timedelta(days=(7 - month_first.weekday()) % 7)
        weeks = []
        while day.month == month_first.month:
            weeks.append(day)
            day += timedelta(days=7)
        return weeks

    def _awards_month_complete(self, month_first, today):
        weeks = self._awards_month_weeks(month_first)
        return bool(weeks) and weeks[-1] + timedelta(days=6) < today

    def _awards_default_month(self):
        """Most recent month whose LAST week has fully ended."""
        today = fields.Date.context_today(self)
        month = date(today.year, today.month, 1)
        for _i in range(3):
            month = self._awards_prev_month(month)
            if self._awards_month_complete(month, today):
                return month
        return month

    def _awards_month_value(self, month_first):
        return "%04d-%02d" % (month_first.year, month_first.month)

    def _awards_month_label(self, month_first):
        return month_first.strftime("%B %Y")

    def _awards_selected_month(self, filters=False):
        filters = filters or {}
        value = filters.get("month")
        if value:
            try:
                year, month = str(value).split("-")[:2]
                return date(int(year), int(month), 1)
            except (TypeError, ValueError):
                pass
        return self._awards_default_month()

    def _awards_month_options(self):
        month = self._awards_default_month()
        options = []
        for _i in range(MONTH_OPTIONS_COUNT):
            options.append(
                {
                    "value": self._awards_month_value(month),
                    "label": self._awards_month_label(month),
                }
            )
            month = self._awards_prev_month(month)
        return options

    def _awards_filter_options(self, filters=False):
        return {
            "enabled": True,
            "months": self._awards_month_options(),
            "selected": self._awards_month_value(self._awards_selected_month(filters)),
        }
