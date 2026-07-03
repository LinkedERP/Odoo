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

    # ------------------------------------------------------------------
    # Weekly series engine (single pass over the YTD weeks)
    # ------------------------------------------------------------------
    def _weekly_blank_rec(self):
        return {"lines": 0, "late": 0, "expected": 0.0, "billable": 0.0, "uids": []}

    def _weekly_series(self):
        """Per-week org + per-team sums for the YTD window.

        Each weekly helper is called exactly once per week; every widget is
        derived from this single pass. Users with no squad tag count in "org"
        only. A week where a user is ineligible contributes nothing for that
        user on either side of any division.
        """
        weeks = self._weekly_ytd_weeks()
        primary_map = self._ops_primary_employees()
        fields_map = self.env["hr.employee"]._fields
        team_by_user = {}
        for uid, emp in primary_map.items():
            value = emp[OPS_SUBTEAM_FIELD] if OPS_SUBTEAM_FIELD in fields_map else False
            if value:
                team_by_user[uid] = value
        team_keys = [value for value, _label in self._awards_team_labels()]

        by_week = {}
        for week in weeks:
            org = self._weekly_blank_rec()
            teams = {key: self._weekly_blank_rec() for key in team_keys}
            emp_map = self._ops_eligible_employees(week, primary_map=primary_map)
            if emp_map:
                uids = list(emp_map.keys())
                expected = self._ops_expected_hours_by_user(week, emp_map=emp_map)
                billable = self._ops_logged_hours_by_user(week, billable_only=True)
                totals, on_time = self._ops_passrate_counts_by_user(week, uids)
                for uid in uids:
                    lines = totals.get(uid, 0)
                    late = lines - on_time.get(uid, 0)
                    targets = [org]
                    team_key = team_by_user.get(uid)
                    if team_key in teams:
                        targets.append(teams[team_key])
                    for rec in targets:
                        rec["lines"] += lines
                        rec["late"] += late
                        rec["expected"] += expected.get(uid, 0.0)
                        rec["billable"] += billable.get(uid, 0.0)
                        rec["uids"].append(uid)
            by_week[week] = {"org": org, "teams": teams}
        return {"weeks": weeks, "by_week": by_week}

    def _weekly_fail_rate(self, rec):
        return round(rec["late"] / rec["lines"] * 100, 1) if rec["lines"] else 0.0

    def _weekly_bill_rate(self, rec):
        den = rec["expected"] * BILLABLE_SHARE
        return round(rec["billable"] / den * 100, 1) if den else 0.0

    def _weekly_sum(self, recs):
        total = self._weekly_blank_rec()
        uids = set()
        for rec in recs:
            total["lines"] += rec["lines"]
            total["late"] += rec["late"]
            total["expected"] += rec["expected"]
            total["billable"] += rec["billable"]
            uids.update(rec["uids"])
        total["uids"] = sorted(uids)
        return total

    def _weekly_scope_records(self, series, week):
        """(org_rec, {squad_key: rec}) for one clicked week, or summed YTD."""
        team_keys = [value for value, _label in self._awards_team_labels()]
        if week and week in series["by_week"]:
            entry = series["by_week"][week]
            return entry["org"], entry["teams"]
        org = self._weekly_sum([series["by_week"][w]["org"] for w in series["weeks"]])
        teams = {
            key: self._weekly_sum(
                [series["by_week"][w]["teams"][key] for w in series["weeks"]]
            )
            for key in team_keys
        }
        return org, teams

    def _weekly_scope_domain(self, week, uids=None, billable_only=False):
        """Timesheet-line domain for the scope. Callers pass uids=[0] for an
        empty population so drill-down opens no records instead of all."""
        weeks = self._weekly_ytd_weeks()
        if week:
            first, last = week, week + timedelta(days=6)
        elif weeks:
            first, last = weeks[0], weeks[-1] + timedelta(days=6)
        else:
            return []
        domain = [
            ("project_id", "!=", False),
            ("date", ">=", fields.Date.to_string(first)),
            ("date", "<=", fields.Date.to_string(last)),
        ]
        if billable_only:
            domain.append(("timesheet_invoice_type", "!=", "non_billable"))
        if uids is not None:
            domain.append(("user_id", "in", uids))
        return domain
