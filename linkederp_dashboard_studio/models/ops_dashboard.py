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

# Optional sub-team ("Operations Team" Studio selection on hr.employee) used as a
# dashboard slicer next to the week filter.
OPS_SUBTEAM_FIELD = "x_studio_selection_field_8lf_1jsfbg0sl"

# Expected billable hours are this share of total expected hours.
BILLABLE_SHARE = 0.75

# Employee eligibility (Studio date fields on hr.employee).
# Ramp-up: expected hours start on the Monday of the week RAMP_WEEKS after joining.
# Exit: expected hours stop after the week before the DOE (Date of Exit) week.
OPS_JOIN_FIELD = "x_studio_date_of_joining"
OPS_EXIT_FIELD = "x_studio_doe"
OPS_RAMP_WEEKS = 4

# Planning always looks this many weeks ahead of the selected week.
PLANNING_WEEKS = 8

# Billability trend looks this many weeks back (including the selected week).
TREND_WEEKS = 8

# Trend bars turn red below this billability/planning %.
TREND_TARGET = 75.0


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

    def _ops_selected_subteam(self, filters=False):
        filters = filters or {}
        return filters.get("ops_team") or ""

    def _ops_subteam_options(self):
        options = [{"value": "", "label": _("All Operations Teams")}]
        Employee = self.env["hr.employee"]
        if OPS_SUBTEAM_FIELD in Employee._fields:
            info = Employee.fields_get([OPS_SUBTEAM_FIELD])
            for value, label in info.get(OPS_SUBTEAM_FIELD, {}).get("selection") or []:
                options.append({"value": value, "label": label})
        return options

    def _ops_filter_options(self, filters=False):
        return {
            "enabled": True,
            "weeks": self._ops_week_options(),
            "selected": fields.Date.to_string(self._ops_selected_week(filters)),
            "teams": self._ops_subteam_options(),
            "selected_team": self._ops_selected_subteam(filters),
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
    def _ops_primary_employees(self, sub_team=None):
        """{user_id: employee} for the employee in the user's DEFAULT company.

        Expected hours (leaves + public holidays) are driven only by this
        default-company employee, even though the user may log time for other
        companies' projects.
        """
        domain = [("user_id", "!=", False), ("active", "=", True)]
        fields_map = self.env["hr.employee"]._fields
        if OPS_TEAM_FIELD in fields_map:
            domain.append((OPS_TEAM_FIELD, "=", OPS_TEAM_VALUE))
        if sub_team and OPS_SUBTEAM_FIELD in fields_map:
            domain.append((OPS_SUBTEAM_FIELD, "=", sub_team))
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

    def _ops_is_employee_eligible(self, employee, week_start):
        """Employee counts for a reviewed week only within their active window.

        - Ramp-up: from the Monday of the week OPS_RAMP_WEEKS after joining.
        - Exit: through the week before the DOE (Date of Exit) week.
        """
        fields_map = self.env["hr.employee"]._fields
        if OPS_JOIN_FIELD in fields_map:
            join_date = employee[OPS_JOIN_FIELD]
            if join_date:
                ramp_start = self._ops_week_start(join_date) + timedelta(days=7 * OPS_RAMP_WEEKS)
                if week_start < ramp_start:
                    return False
        if OPS_EXIT_FIELD in fields_map:
            exit_date = employee[OPS_EXIT_FIELD]
            if exit_date:
                last_week = self._ops_week_start(exit_date) - timedelta(days=7)
                if week_start > last_week:
                    return False
        return True

    def _ops_eligible_employees(self, week_start, sub_team=None, primary_map=None):
        """{user_id: employee} restricted to those eligible for the given week."""
        if primary_map is None:
            primary_map = self._ops_primary_employees(sub_team=sub_team)
        return {
            uid: emp
            for uid, emp in primary_map.items()
            if self._ops_is_employee_eligible(emp, week_start)
        }

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

    def _ops_logged_hours_by_user(self, week_start, billable_only=False):
        """{user_id: logged project hours} across all companies for the week.

        billable_only keeps lines whose invoice type is not ``non_billable``.
        """
        week_end = week_start + timedelta(days=6)
        domain = [
            ("project_id", "!=", False),
            ("date", ">=", fields.Date.to_string(week_start)),
            ("date", "<=", fields.Date.to_string(week_end)),
        ]
        if billable_only:
            domain.append(("timesheet_invoice_type", "!=", "non_billable"))
        rows = self.env["account.analytic.line"].with_context(active_test=False).read_group(
            domain,
            ["unit_amount:sum"],
            ["user_id"],
            lazy=False,
        )
        return {
            row["user_id"][0]: (row.get("unit_amount") or 0.0)
            for row in rows
            if row.get("user_id")
        }

    def _ops_billable_domain(self, week_start):
        return self._ops_timesheet_week_domain(week_start) + [
            ("timesheet_invoice_type", "!=", "non_billable")
        ]

    def _ops_billability(self, week_start, emp_map=None):
        """Team billability = billable hours / (75% of expected hours)."""
        expected = self._ops_expected_hours_by_user(week_start, emp_map=emp_map)
        billable = self._ops_logged_hours_by_user(week_start, billable_only=True)
        population = list(expected.keys())
        expected_billable = sum(expected.values()) * BILLABLE_SHARE
        total_billable = sum(billable.get(uid, 0.0) for uid in population)
        rate = round(total_billable / expected_billable * 100, 1) if expected_billable else 0.0
        return rate, total_billable, expected_billable

    def _ops_planned_hours_by_user(self, week_start):
        """{user_id: planned hours} from planning slots starting in the week."""
        if "planning.slot" not in self.env:
            return {}
        week_end = week_start + timedelta(days=6)
        rows = self.env["planning.slot"].read_group(
            [
                ("user_id", "!=", False),
                ("start_datetime", ">=", "%s 00:00:00" % fields.Date.to_string(week_start)),
                ("start_datetime", "<=", "%s 23:59:59" % fields.Date.to_string(week_end)),
            ],
            ["allocated_hours:sum"],
            ["user_id"],
            lazy=False,
        )
        return {
            row["user_id"][0]: (row.get("allocated_hours") or 0.0)
            for row in rows
            if row.get("user_id")
        }

    def _ops_planning_series(self, selected_week, primary_map):
        """Per-week [{week, expected, planned, users}] for the next PLANNING_WEEKS weeks."""
        weeks = [selected_week + timedelta(days=7 * i) for i in range(1, PLANNING_WEEKS + 1)]
        return self._ops_hours_series(weeks, primary_map, planned=True)

    def _ops_billability_series(self, selected_week, primary_map):
        """Per-week [{week, expected, billable, users}] for the last TREND_WEEKS weeks."""
        weeks = [selected_week - timedelta(days=7 * i) for i in range(TREND_WEEKS - 1, -1, -1)]
        return self._ops_hours_series(weeks, primary_map, billable=True)

    def _ops_hours_series(self, weeks, primary_map, planned=False, billable=False):
        series = []
        for week in weeks:
            emp_map = self._ops_eligible_employees(week, primary_map=primary_map)
            expected = self._ops_expected_hours_by_user(week, emp_map=emp_map)
            population = list(expected.keys())
            row = {
                "week": week,
                "expected": sum(expected.values()),
                "users": population,
            }
            if planned:
                slots = self._ops_planned_hours_by_user(week)
                row["planned"] = sum(slots.get(uid, 0.0) for uid in population)
            if billable:
                bill = self._ops_logged_hours_by_user(week, billable_only=True)
                row["billable"] = sum(bill.get(uid, 0.0) for uid in population)
            series.append(row)
        return series

    def _ops_trend_color(self, rate):
        return "#2e7d2e" if rate >= 75 else "#b03030"

    def _ops_marker_color(self, rate):
        return "#2e7d2e" if rate >= 100 else "#b03030"

    def _ops_time_entry_series(self, selected_week, primary_map):
        """Return (pass_points, coverage_points) for the last TREND_WEEKS weeks."""
        weeks = [selected_week - timedelta(days=7 * i) for i in range(TREND_WEEKS - 1, -1, -1)]
        pass_points = []
        cov_points = []
        for week in weeks:
            emp_map = self._ops_eligible_employees(week, primary_map=primary_map)
            uids = list(emp_map.keys())
            label = self._ops_week_num(week)

            prate, _on, _tot, _cutoff, pass_domain = self._ops_pass_rate(week, user_ids=uids)
            pass_points.append({
                "label": label,
                "value": prate,
                "color": self._ops_marker_color(prate),
                "domain": self._json_safe(pass_domain),
            })

            crate, _logged, _expected = self._ops_coverage(week, emp_map=emp_map)
            cov_domain = self._ops_timesheet_week_domain(week)
            if uids:
                cov_domain = cov_domain + [("user_id", "in", uids)]
            cov_points.append({
                "label": label,
                "value": crate,
                "color": self._ops_marker_color(crate),
                "domain": self._json_safe(cov_domain),
            })
        return pass_points, cov_points

    def _ops_trendline_widget(self, wid, name, model, points):
        return {
            "id": wid,
            "name": name,
            "type": "trendline",
            "model": model,
            "mode": "computed",
            "measure": "",
            "groupby": "",
            "color": "#38bdf8",
            "help": "",
            "value": float(points[-1]["value"]) if points else 0.0,
            "format": "percent",
            "domain": points[-1]["domain"] if points else [],
            "points": points,
            "rows": [],
            "columns": [],
            "span": 4,
            "error": False,
        }

    def _ops_week_num(self, week_start):
        return "W%02d" % week_start.isocalendar()[1]

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
        sub_team = self._ops_selected_subteam(filters)
        primary_map = self._ops_primary_employees(sub_team=sub_team)
        emp_map = self._ops_eligible_employees(week_start, primary_map=primary_map)
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
            "help": _("on time ≤ %s") % cutoff.strftime("%d %b"),
            "value": float(rate),
            "format": "percent",
            "domain": self._json_safe(pass_domain),
            "points": [],
            "rows": [],
            "columns": [],
            "span": 2,
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
            "help": _("logged vs expected"),
            "value": float(cov_rate),
            "format": "percent",
            "domain": self._json_safe(coverage_domain),
            "points": [],
            "rows": [],
            "columns": [],
            "span": 2,
            "error": False,
        }

        # Time-entry trend lines (last 8 weeks) next to each KPI card.
        pass_points, cov_points = self._ops_time_entry_series(week_start, primary_map)
        pass_trend = self._ops_trendline_widget(
            "ops_pass_trend", _("Pass Rate trend"), "account.analytic.line", pass_points
        )
        coverage_trend = self._ops_trendline_widget(
            "ops_coverage_trend", _("Coverage trend"), "account.analytic.line", cov_points
        )

        # Trend charts (each carries its own avg % badge; the standalone
        # Billability / Planning cards were folded into these).
        billability_trend = self._ops_trend_widget(
            "ops_billability_trend",
            _("Billability — last 8 weeks"),
            "account.analytic.line",
            self._ops_billability_series(week_start, primary_map),
            kind="billable",
        )
        planning_trend = self._ops_trend_widget(
            "ops_planning_trend",
            _("Planning — next 8 weeks"),
            "planning.slot",
            self._ops_planning_series(week_start, primary_map),
            kind="planned",
        )

        return [
            pass_card,
            pass_trend,
            coverage_card,
            coverage_trend,
            billability_trend,
            planning_trend,
        ]

    def _ops_trend_widget(self, wid, name, model, series, kind):
        points = []
        total_num = 0.0
        total_den = 0.0
        for row in series:
            week = row["week"]
            if kind == "billable":
                den = row["expected"] * BILLABLE_SHARE
                num = row["billable"]
                domain = self._ops_billable_domain(week)
            else:
                den = row["expected"]
                num = row["planned"]
                domain = [
                    ("start_datetime", ">=", "%s 00:00:00" % fields.Date.to_string(week)),
                    ("start_datetime", "<=", "%s 23:59:59" % fields.Date.to_string(week + timedelta(days=6))),
                ]
            value = round(num / den * 100, 1) if den else 0.0
            total_num += num
            total_den += den
            if row["users"]:
                domain = domain + [("user_id", "in", row["users"])]
            points.append({
                "label": self._ops_week_num(week),
                "value": value,
                "color": self._ops_trend_color(value),
                "domain": self._json_safe(domain),
            })
        avg = round(total_num / total_den * 100, 1) if total_den else 0.0
        return {
            "id": wid,
            "name": name,
            "type": "column",
            "model": model,
            "mode": "computed",
            "measure": "%",
            "groupby": _("Week"),
            "color": "#2e7d2e",
            "help": _("Team %(team)s · red below %(target)s%%") % {
                "team": OPS_TEAM_VALUE,
                "target": self._ops_short_hours(TREND_TARGET),
            },
            "value": float(avg),
            "format": "percent",
            "domain": [],
            "points": points,
            "rows": [],
            "columns": [],
            "span": 6,
            "error": False,
            "badge": _("avg %s%%") % self._ops_short_hours(avg),
            "target": TREND_TARGET,
        }

    def _ops_short_hours(self, hours):
        hours = round(hours or 0, 1)
        if hours == int(hours):
            return "%d" % int(hours)
        return "%.1f" % hours
