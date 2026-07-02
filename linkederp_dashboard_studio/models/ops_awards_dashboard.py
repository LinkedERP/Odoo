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

    # ------------------------------------------------------------------
    # Monthly scoreboard
    # ------------------------------------------------------------------
    def _awards_team_labels(self):
        """Squad selection [(value, label), ...] from the Operations Team field."""
        Employee = self.env["hr.employee"]
        if OPS_SUBTEAM_FIELD not in Employee._fields:
            return []
        info = Employee.fields_get([OPS_SUBTEAM_FIELD])
        return info.get(OPS_SUBTEAM_FIELD, {}).get("selection") or []

    def _awards_score(self, bill_rate, ontime_rate):
        """Overall score out of 100: billability capped at 100, 50/50 with on-time."""
        return (min(bill_rate, 100.0) + ontime_rate) / 2.0

    def _awards_scoreboard(self, month_first):
        """Aggregate the weekly KPIs over the month's weeks.

        Numerators and denominators are summed across weeks BEFORE dividing
        (hour-weighted). Every squad appears in "teams" even with no members.
        Employees need >= AWARDS_MIN_ELIGIBLE_WEEKS eligible weeks; exception
        resources (expected = actual) are kept in team totals but dropped from
        the employee list.
        """
        weeks = self._awards_month_weeks(month_first)
        primary_map = self._ops_primary_employees()
        exception_uids = set(self._ops_exception_user_ids(primary_map))

        per_user = {}
        for week in weeks:
            emp_map = self._ops_eligible_employees(week, primary_map=primary_map)
            if not emp_map:
                continue
            uids = list(emp_map.keys())
            expected = self._ops_expected_hours_by_user(week, emp_map=emp_map)
            billable = self._ops_logged_hours_by_user(week, billable_only=True)
            totals, on_time = self._ops_passrate_counts_by_user(week, uids)
            for uid in uids:
                rec = per_user.setdefault(
                    uid,
                    {"expected": 0.0, "billable": 0.0, "lines": 0, "on_time": 0, "weeks": 0},
                )
                rec["expected"] += expected.get(uid, 0.0)
                rec["billable"] += billable.get(uid, 0.0)
                rec["lines"] += totals.get(uid, 0)
                rec["on_time"] += on_time.get(uid, 0)
                rec["weeks"] += 1

        def rates(expected, billable, lines, on_time):
            expected_billable = expected * BILLABLE_SHARE
            bill = billable / expected_billable * 100 if expected_billable else 0.0
            ontime = on_time / lines * 100 if lines else 0.0
            return round(bill, 1), round(ontime, 1)

        fields_map = self.env["hr.employee"]._fields
        team_by_user = {}
        for uid, emp in primary_map.items():
            value = emp[OPS_SUBTEAM_FIELD] if OPS_SUBTEAM_FIELD in fields_map else False
            if value:
                team_by_user[uid] = value

        teams = []
        for value, label in self._awards_team_labels():
            member_uids = [
                uid for uid, team in team_by_user.items()
                if team == value and uid in per_user
            ]
            expected = sum(per_user[uid]["expected"] for uid in member_uids)
            billable = sum(per_user[uid]["billable"] for uid in member_uids)
            lines = sum(per_user[uid]["lines"] for uid in member_uids)
            on_time = sum(per_user[uid]["on_time"] for uid in member_uids)
            bill, ontime = rates(expected, billable, lines, on_time)
            teams.append(
                {
                    "key": value,
                    "label": label,
                    "uids": member_uids,
                    "bill": bill,
                    "ontime": ontime,
                    "score": self._awards_score(bill, ontime),
                }
            )
        teams.sort(key=lambda team: (-team["score"], team["label"].lower()))
        for index, team in enumerate(teams):
            team["rank"] = index + 1

        employees = []
        for uid, rec in per_user.items():
            if uid in exception_uids or rec["weeks"] < AWARDS_MIN_ELIGIBLE_WEEKS:
                continue
            employee = primary_map.get(uid)
            bill, ontime = rates(rec["expected"], rec["billable"], rec["lines"], rec["on_time"])
            employees.append(
                {
                    "uid": uid,
                    "name": employee.user_id.name if employee else _("Unknown"),
                    "team": team_by_user.get(uid, ""),
                    "bill": bill,
                    "ontime": ontime,
                    "score": self._awards_score(bill, ontime),
                }
            )
        employees.sort(key=lambda emp: (-emp["score"], -emp["bill"], emp["name"].lower()))
        for index, employee in enumerate(employees):
            employee["rank"] = index + 1

        return {
            "month_first": month_first,
            "weeks": weeks,
            "teams": teams,
            "employees": employees,
        }
