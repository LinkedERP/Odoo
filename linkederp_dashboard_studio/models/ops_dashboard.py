import logging
from datetime import datetime, time, timedelta

from pytz import utc

from odoo import fields, models, _

_logger = logging.getLogger(__name__)

OPS_DASHBOARD_NAME = "Ops Performance"

# How many past weeks to offer in the week selector.
WEEK_OPTIONS_COUNT = 26

# Restrict the dashboard to a single team. This is the Studio "Team" selection
# field on hr.employee; the filter is applied against the user's default-company
# employee, and is skipped automatically on databases without the field.
OPS_TEAM_FIELD = "x_studio_selection_field_ih_1jsfannnb"
OPS_TEAM_VALUE = "Operations"


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

    def _ops_pass_rate(self, week_start, user_ids=None):
        """Return (rate, on_time, total, cutoff_date, base_domain).

        Pass = a project timesheet line dated in the reviewed week whose
        Created-on date is on/before the Monday of the following week.
        Counted across all companies, optionally restricted to a set of users.
        """
        cutoff = week_start + timedelta(days=7)  # Monday of the following week
        base = self._ops_timesheet_week_domain(week_start)
        if user_ids is not None:
            base = base + [("user_id", "in", user_ids)]
        Line = self.env["account.analytic.line"].with_context(active_test=False)
        total = Line.search_count(base)
        on_time = Line.search_count(
            base + [("create_date", "<=", "%s 23:59:59" % fields.Date.to_string(cutoff))]
        )
        rate = round(on_time / total * 100, 1) if total else 0.0
        return rate, on_time, total, cutoff, base

    def _ops_pass_rate_color(self, rate):
        if rate >= 100:
            return "#2e7d2e"
        if rate >= 90:
            return "#c98a1b"
        return "#b03030"

    # ------------------------------------------------------------------
    # Expected hours (reusable engine) + Coverage
    # ------------------------------------------------------------------
    def _ops_primary_employees(self):
        """{user_id: employee} for the employee in the user's DEFAULT company.

        Expected hours (leaves + public holidays) are driven only by this
        default-company employee, even though the user may log time for other
        companies' projects.
        """
        domain = [("user_id", "!=", False), ("active", "=", True)]
        if OPS_TEAM_FIELD in self.env["hr.employee"]._fields:
            domain.append((OPS_TEAM_FIELD, "=", OPS_TEAM_VALUE))
        employees = self.env["hr.employee"].search(domain)
        by_user_company = {}
        for emp in employees:
            by_user_company.setdefault((emp.user_id.id, emp.company_id.id), emp)
        result = {}
        for emp in employees:
            user = emp.user_id
            primary = by_user_company.get((user.id, user.company_id.id))
            if primary:
                result[user.id] = primary
        return result

    def _ops_employee_expected_hours(self, employees, week_start, week_end):
        """{employee_id: expected hours} net of leaves & public holidays."""
        if not employees:
            return {}
        start_dt = utc.localize(datetime.combine(week_start, time.min))
        end_dt = utc.localize(datetime.combine(week_end, time.max))
        try:
            data = employees._get_work_days_data_batch(
                start_dt, end_dt, compute_leaves=True
            )
            return {emp_id: (vals or {}).get("hours", 0.0) for emp_id, vals in data.items()}
        except Exception:
            _logger.exception("Ops dashboard: expected-hours batch failed, using fallback")
            return self._ops_expected_hours_fallback(employees, week_start, week_end)

    def _ops_expected_hours_fallback(self, employees, week_start, week_end):
        """Coarse fallback: calendar hours/day x working weekdays, minus leave days."""
        days = [week_start + timedelta(days=d) for d in range((week_end - week_start).days + 1)]
        Leaves = self.env["resource.calendar.leaves"]
        result = {}
        for emp in employees:
            calendar = emp.resource_calendar_id
            if not calendar:
                result[emp.id] = 0.0
                continue
            hours_per_day = calendar.hours_per_day or 8.0
            attn_days = {int(a.dayofweek) for a in calendar.attendance_ids if a.day_period != "lunch"}
            work_days = [d for d in days if d.weekday() in attn_days]
            leave_domain = [
                ("date_from", "<=", "%s 23:59:59" % fields.Date.to_string(week_end)),
                ("date_to", ">=", "%s 00:00:00" % fields.Date.to_string(week_start)),
                "|",
                ("resource_id", "=", emp.resource_id.id),
                "&",
                ("resource_id", "=", False),
                ("calendar_id", "=", calendar.id),
            ]
            covered = set()
            for leave in Leaves.search(leave_domain):
                lstart = fields.Datetime.to_datetime(leave.date_from).date()
                lend = fields.Datetime.to_datetime(leave.date_to).date()
                for day in work_days:
                    if lstart <= day <= lend:
                        covered.add(day)
            result[emp.id] = max(0.0, (len(work_days) - len(covered)) * hours_per_day)
        return result

    def _ops_expected_hours_by_user(self, week_start, emp_map=None):
        """{user_id: expected hours} for the reviewed week."""
        if emp_map is None:
            emp_map = self._ops_primary_employees()
        if not emp_map:
            return {}
        employees = self.env["hr.employee"].browse([emp.id for emp in emp_map.values()])
        week_end = week_start + timedelta(days=6)
        by_emp = self._ops_employee_expected_hours(employees, week_start, week_end)
        return {uid: by_emp.get(emp.id, 0.0) for uid, emp in emp_map.items()}

    def _ops_logged_hours_by_user(self, week_start):
        """{user_id: logged project hours} across all companies for the week."""
        week_end = week_start + timedelta(days=6)
        rows = self.env["account.analytic.line"].with_context(active_test=False).read_group(
            [
                ("project_id", "!=", False),
                ("date", ">=", fields.Date.to_string(week_start)),
                ("date", "<=", fields.Date.to_string(week_end)),
            ],
            ["unit_amount:sum"],
            ["user_id"],
            lazy=False,
        )
        return {
            row["user_id"][0]: (row.get("unit_amount") or 0.0)
            for row in rows
            if row.get("user_id")
        }

    def _ops_coverage(self, week_start, emp_map=None):
        """Team coverage = logged hours / expected hours over the delivery team."""
        expected = self._ops_expected_hours_by_user(week_start, emp_map=emp_map)
        logged = self._ops_logged_hours_by_user(week_start)
        population = list(expected.keys())
        total_expected = sum(expected.values())
        total_logged = sum(logged.get(uid, 0.0) for uid in population)
        rate = round(total_logged / total_expected * 100, 1) if total_expected else 0.0
        return rate, total_logged, total_expected

    def _ops_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        week_start = self._ops_selected_week(filters)
        emp_map = self._ops_primary_employees()
        team_user_ids = list(emp_map.keys())

        rate, on_time, total, cutoff, pass_domain = self._ops_pass_rate(
            week_start, user_ids=team_user_ids
        )

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
            "help": _("Team %(team)s · reviewed %(week)s · on time = created on/before %(cutoff)s") % {
                "team": OPS_TEAM_VALUE,
                "week": self._ops_week_label(week_start),
                "cutoff": cutoff.strftime("%d %b %Y"),
            },
            "value": float(rate),
            "format": "percent",
            "domain": self._json_safe(pass_domain),
            "points": [],
            "rows": [],
            "columns": [],
            "span": 3,
            "error": False,
        }

        cov_rate, logged_hours, expected_hours = self._ops_coverage(week_start, emp_map=emp_map)
        coverage_domain = self._ops_timesheet_week_domain(week_start)
        if team_user_ids:
            coverage_domain = coverage_domain + [("user_id", "in", team_user_ids)]
        coverage_card = {
            "id": "ops_coverage",
            "name": _("Time Entry Coverage"),
            "type": "kpi",
            "model": "account.analytic.line",
            "mode": "computed",
            "measure": _("%(logged)s / %(expected)s hrs logged") % {
                "logged": self._ops_short_hours(logged_hours),
                "expected": self._ops_short_hours(expected_hours),
            },
            "groupby": "",
            "color": self._ops_pass_rate_color(cov_rate),
            "help": _("Team %(team)s · reviewed %(week)s · hours logged (all companies) vs "
                      "expected (default-company calendar, leaves & holidays removed)") % {
                "team": OPS_TEAM_VALUE,
                "week": self._ops_week_label(week_start),
            },
            "value": float(cov_rate),
            "format": "percent",
            "domain": self._json_safe(coverage_domain),
            "points": [],
            "rows": [],
            "columns": [],
            "span": 3,
            "error": False,
        }
        return [pass_card, coverage_card]

    def _ops_short_hours(self, hours):
        hours = round(hours or 0, 1)
        if hours == int(hours):
            return "%d" % int(hours)
        return "%.1f" % hours
