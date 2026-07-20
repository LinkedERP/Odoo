import logging
from datetime import datetime, time, timedelta

from pytz import utc

from odoo import fields, models, _

_logger = logging.getLogger(__name__)

OPS_DASHBOARD_NAME = "Ops Weekly review"
OPS_DASHBOARD_LEGACY = "Ops Performance"

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

# "Manages Team" Studio selection on hr.employee: maps a squad to its team lead
# (project manager). Used to filter the project list by project manager.
OPS_MANAGES_FIELD = "x_manages_team"

# Project stages excluded from the project list.
OPS_EXCLUDED_STAGES = ["Done", "On Hold", "Cancelled", "Internal", "Support"]

# Expected billable hours are this share of total expected hours.
BILLABLE_SHARE = 0.75

# Exception resources whose expected hours always equal their actual logged
# hours (matched on a name token, case-insensitive), so their coverage is 100%.
OPS_EXPECTED_EQUALS_ACTUAL = ("ferry", "imke")

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

# Project-margin WoW trend: weeks shown in the profitability popup.
PROF_TREND_WEEKS = 6


class LinkederpDashboardOps(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_ops_dashboard()

    def _ensure_ops_dashboard(self):
        if self._ensure_dashboard_name(OPS_DASHBOARD_NAME, [OPS_DASHBOARD_LEGACY]):
            return
        if "account.analytic.line" not in self.env:
            return
        self.create(
            {
                "name": OPS_DASHBOARD_NAME,
                "sequence": 30,
                "bucket": "ops",
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

    def _ops_exception_user_ids(self, emp_map):
        """Users whose expected hours always equal their actual logged hours."""
        result = []
        for uid, emp in emp_map.items():
            tokens = (emp.user_id.name or "").lower().replace(",", " ").split()
            if any(token in OPS_EXPECTED_EQUALS_ACTUAL for token in tokens):
                result.append(uid)
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
        result = {uid: by_emp.get(emp.id, 0.0) for uid, emp in emp_map.items()}
        # Exception resources: expected hours = actual logged hours.
        exception_uids = self._ops_exception_user_ids(emp_map)
        if exception_uids:
            logged = self._ops_logged_hours_by_user(week_start)
            for uid in exception_uids:
                result[uid] = logged.get(uid, 0.0)
        return result

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
        """Team billability = billable hours / expected billable hours.

        Expected billable = 75% of expected hours; exception resources count
        their ACTUAL billable hours as expected billable (always 100%),
        mirroring the total-expected rule (per Akshay, 2026-07-03)."""
        if emp_map is None:
            emp_map = self._ops_primary_employees()
        expected = self._ops_expected_hours_by_user(week_start, emp_map=emp_map)
        billable = self._ops_logged_hours_by_user(week_start, billable_only=True)
        exception_uids = set(self._ops_exception_user_ids(emp_map))
        population = list(expected.keys())
        expected_billable = sum(
            (billable.get(uid, 0.0) if uid in exception_uids else exp * BILLABLE_SHARE)
            for uid, exp in expected.items()
        )
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
            if planned:
                actual = self._ops_planned_hours_by_user(week)
            else:
                actual = self._ops_logged_hours_by_user(week, billable_only=True)
            series.append({
                "week": week,
                "users": list(expected.keys()),
                "names": self._ops_names_map(emp_map),
                "expected_by_user": expected,
                "actual_by_user": actual,
                "exception_uids": self._ops_exception_user_ids(emp_map),
            })
        return series

    def _ops_trend_color(self, rate):
        return "#2e7d2e" if rate >= 75 else "#b03030"

    def _ops_marker_color(self, rate):
        return "#2e7d2e" if rate >= 100 else "#b03030"

    # ------------------------------------------------------------------
    # Per-employee hover detail
    # ------------------------------------------------------------------
    def _ops_names_map(self, emp_map):
        return {uid: emp.user_id.name for uid, emp in emp_map.items()}

    def _ops_detail_payload(self, uids, names, expected, actual, headers,
                            expected_factor=1.0, integer=False, max_rows=15):
        """Employee-level table for a tooltip: {cols, rows, total, more}."""
        def fmt(value):
            return "%d" % round(value) if integer else self._ops_short_hours(value)

        data = []
        total_e = 0.0
        total_a = 0.0
        for uid in uids:
            exp = expected.get(uid, 0.0) * expected_factor
            act = actual.get(uid, 0.0)
            total_e += exp
            total_a += act
            data.append((names.get(uid, _("Unknown")), exp, act))
        data.sort(key=lambda item: (-item[1], item[0].lower()))

        rows = []
        for name, exp, act in data[:max_rows]:
            pct = round(act / exp * 100, 1) if exp else 0.0
            rows.append({"name": name, "cells": [fmt(exp), fmt(act), "%s%%" % self._ops_short_hours(pct)]})
        more = _("+%s more") % (len(data) - max_rows) if len(data) > max_rows else ""
        total_pct = round(total_a / total_e * 100, 1) if total_e else 0.0
        total = {
            "name": _("Total"),
            "cells": [fmt(total_e), fmt(total_a), "%s%%" % self._ops_short_hours(total_pct)],
        }
        return {"cols": headers, "rows": rows, "total": total, "more": more}

    def _ops_passrate_counts_by_user(self, week_start, uids):
        """({user_id: total lines}, {user_id: on-time lines}) for the week."""
        cutoff = week_start + timedelta(days=7)
        base = self._ops_timesheet_week_domain(week_start)
        if uids:
            base = base + [("user_id", "in", uids)]
        Line = self.env["account.analytic.line"].with_context(active_test=False)
        totals = Line.read_group(base, ["__count"], ["user_id"], lazy=False)
        on_time = Line.read_group(
            base + [("create_date", "<=", "%s 23:59:59" % fields.Date.to_string(cutoff))],
            ["__count"], ["user_id"], lazy=False,
        )
        total_by_user = {r["user_id"][0]: r.get("__count", 0) for r in totals if r.get("user_id")}
        ontime_by_user = {r["user_id"][0]: r.get("__count", 0) for r in on_time if r.get("user_id")}
        return total_by_user, ontime_by_user

    def _ops_time_entry_series(self, selected_week, primary_map):
        """Return (pass_points, coverage_points) for the last TREND_WEEKS weeks."""
        weeks = [selected_week - timedelta(days=7 * i) for i in range(TREND_WEEKS - 1, -1, -1)]
        pass_points = []
        cov_points = []
        for week in weeks:
            emp_map = self._ops_eligible_employees(week, primary_map=primary_map)
            uids = list(emp_map.keys())
            names = self._ops_names_map(emp_map)
            label = self._ops_week_num(week)

            # Pass rate (line-count based, per user).
            total_lines, ontime_lines = self._ops_passrate_counts_by_user(week, uids)
            tot = sum(total_lines.values())
            on = sum(ontime_lines.values())
            prate = round(on / tot * 100, 1) if tot else 0.0
            pass_domain = self._ops_timesheet_week_domain(week)
            if uids:
                pass_domain = pass_domain + [("user_id", "in", uids)]
            pass_points.append({
                "label": label,
                "value": prate,
                "color": self._ops_marker_color(prate),
                "domain": self._json_safe(pass_domain),
                "detail": self._ops_detail_payload(
                    uids, names, total_lines, ontime_lines,
                    [_("Lines"), _("On time"), _("%")], integer=True,
                ),
            })

            # Coverage (logged hours vs expected hours, per user).
            expected = self._ops_expected_hours_by_user(week, emp_map=emp_map)
            logged = self._ops_logged_hours_by_user(week)
            total_e = sum(expected.values())
            total_l = sum(logged.get(uid, 0.0) for uid in uids)
            crate = round(total_l / total_e * 100, 1) if total_e else 0.0
            cov_domain = self._ops_timesheet_week_domain(week)
            if uids:
                cov_domain = cov_domain + [("user_id", "in", uids)]
            cov_points.append({
                "label": label,
                "value": crate,
                "color": self._ops_marker_color(crate),
                "domain": self._json_safe(cov_domain),
                "detail": self._ops_detail_payload(
                    uids, names, expected, logged,
                    [_("Expected h"), _("Actual h"), _("%")],
                ),
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

    # ------------------------------------------------------------------
    # SLA / Helpdesk
    # ------------------------------------------------------------------
    def _ops_networkdays(self, start_date, end_date):
        """Excel-style NETWORKDAYS: working days (Mon-Fri) between the two
        dates, inclusive of both ends."""
        if not start_date or start_date > end_date:
            return 0
        total_days = (end_date - start_date).days + 1
        full_weeks, remainder = divmod(total_days, 7)
        working = full_weeks * 5
        start_weekday = start_date.weekday()
        for offset in range(remainder):
            if (start_weekday + offset) % 7 < 5:
                working += 1
        return working

    def _ops_sla_card(self, wid, name, ticket_ids, color, caption):
        return {
            "id": wid,
            "name": name,
            "type": "kpi",
            "model": "helpdesk.ticket",
            "mode": "computed",
            "measure": caption,
            "groupby": "",
            "color": color,
            "help": "",
            "value": float(len(ticket_ids)),
            "format": "integer",
            "domain": self._json_safe([("id", "in", ticket_ids)]),
            "points": [],
            "rows": [],
            "columns": [],
            "span": 4,
            "error": False,
        }

    def _ops_sla_widgets(self, sub_team):
        if "helpdesk.ticket" not in self.env:
            return []
        Stage = self.env["helpdesk.stage"]
        closed_ids = Stage.search([("fold", "=", True)]).ids
        onhold_ids = Stage.search([("name", "ilike", "hold")]).ids

        domain = []
        if closed_ids:
            domain.append(("stage_id", "not in", closed_ids))
        if sub_team:
            member_uids = list(self._ops_primary_employees(sub_team=sub_team).keys())
            domain.append(("user_id", "in", member_uids))

        today = fields.Date.context_today(self)
        tickets = self.env["helpdesk.ticket"].search_read(
            domain, ["stage_id", "create_date", "commercial_partner_id"]
        )

        ids_610, ids_g10, ids_hold = [], [], []
        customers = {}
        for ticket in tickets:
            stage = ticket["stage_id"][0] if ticket["stage_id"] else False
            if stage in onhold_ids:
                ids_hold.append(ticket["id"])
                continue
            age = self._ops_networkdays(fields.Date.to_date(ticket["create_date"]), today)
            if 6 <= age <= 10:
                key = "d610"
                ids_610.append(ticket["id"])
            elif age > 10:
                key = "dg10"
                ids_g10.append(ticket["id"])
            else:
                continue
            partner = ticket["commercial_partner_id"]
            pid = partner[0] if partner else 0
            record = customers.setdefault(
                pid, {"name": partner[1] if partner else _("Unknown"), "d610": [], "dg10": []}
            )
            record[key].append(ticket["id"])

        rows = []
        for record in customers.values():
            rows.append({
                "label": record["name"],
                "d610": len(record["d610"]),
                "dg10": len(record["dg10"]),
                "domain": self._json_safe([("id", "in", record["d610"] + record["dg10"])]),
            })
        rows.sort(key=lambda row: (-row["dg10"], -row["d610"], row["label"].lower()))

        table = {
            "id": "ops_sla_customers",
            "name": _("Ageing tickets by customer"),
            "type": "matrix",
            "model": "helpdesk.ticket",
            "mode": "computed",
            "measure": "",
            "groupby": _("Customer"),
            "color": "#1d4ed8",
            "help": _("open, not on hold · ageing = working days since created"),
            "value": float(len(rows)),
            "format": "integer",
            "domain": [],
            "points": [],
            "rows": rows,
            "columns": [
                {"key": "d610", "label": _("6-10 Days"), "format": "integer"},
                {"key": "dg10", "label": _(">10 Days"), "format": "integer"},
            ],
            "span": 12,
            "error": False,
        }
        return [
            self._ops_sla_card("ops_sla_610", _("Open 6–10 Days"), ids_610, "#c98a1b",
                               _("open 6–10 working days")),
            self._ops_sla_card("ops_sla_g10", _("Open >10 Days"), ids_g10, "#b03030",
                               _("open more than 10 working days")),
            self._ops_sla_card("ops_sla_hold", _("On Hold Tickets"), ids_hold, "#c98a1b",
                               _("tickets on hold")),
            table,
        ]

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
            "ops_pass_trend", _("Pass Rate — last 8 weeks"), "account.analytic.line", pass_points
        )
        coverage_trend = self._ops_trendline_widget(
            "ops_coverage_trend", _("Coverage — last 8 weeks"), "account.analytic.line", cov_points
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

        project_review = self._ops_project_widget(sub_team)

        return [
            pass_card,
            pass_trend,
            coverage_card,
            coverage_trend,
            billability_trend,
            planning_trend,
            project_review,
        ] + self._ops_sla_widgets(sub_team)

    def _ops_trend_widget(self, wid, name, model, series, kind):
        points = []
        total_num = 0.0
        total_den = 0.0
        for row in series:
            week = row["week"]
            uids = row["users"]
            expected = row["expected_by_user"]
            actual = row["actual_by_user"]
            num = sum(actual.get(uid, 0.0) for uid in uids)
            if kind == "billable":
                # Exception resources (expected = actual): their expected
                # BILLABLE hours equal their actual billable hours, mirroring
                # the total-expected rule (per Akshay, 2026-07-03).
                exception_uids = set(row.get("exception_uids") or [])
                exp_bill = {
                    uid: (actual.get(uid, 0.0) if uid in exception_uids
                          else expected.get(uid, 0.0) * BILLABLE_SHARE)
                    for uid in expected
                }
                den = sum(exp_bill.values())
                domain = self._ops_billable_domain(week)
                detail = self._ops_detail_payload(
                    uids, row["names"], exp_bill, actual,
                    [_("Exp. bill h"), _("Billable h"), _("%")],
                )
            else:
                den = sum(expected.values())
                domain = [
                    ("start_datetime", ">=", "%s 00:00:00" % fields.Date.to_string(week)),
                    ("start_datetime", "<=", "%s 23:59:59" % fields.Date.to_string(week + timedelta(days=6))),
                ]
                detail = self._ops_detail_payload(
                    uids, row["names"], expected, actual,
                    [_("Expected h"), _("Planned h"), _("%")],
                )
            value = round(num / den * 100, 1) if den else 0.0
            total_num += num
            total_den += den
            if uids:
                domain = domain + [("user_id", "in", uids)]
            points.append({
                "label": self._ops_week_num(week),
                "value": value,
                "color": self._ops_trend_color(value),
                "domain": self._json_safe(domain),
                "detail": detail,
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

    # ------------------------------------------------------------------
    # Project review
    # ------------------------------------------------------------------
    def _ops_lead_employees(self, sub_team=None):
        """Employees flagged as team leads (Manages Team), optionally one squad."""
        Employee = self.env["hr.employee"]
        if OPS_MANAGES_FIELD not in Employee._fields:
            return Employee.browse()
        domain = [(OPS_MANAGES_FIELD, "!=", False)]
        if sub_team:
            domain = [(OPS_MANAGES_FIELD, "=", sub_team)]
        return Employee.search(domain)

    def _ops_lead_user_ids(self, sub_team=None):
        return list({emp.user_id.id for emp in self._ops_lead_employees(sub_team) if emp.user_id})

    def _ops_money(self, amount, currency):
        symbol = currency.symbol or currency.name or ""
        text = "{:,.0f}".format(round(amount or 0))
        if currency.position == "after":
            return "%s %s" % (text, symbol)
        return "%s%s" % (symbol, text)

    def _ops_pct_text(self, value):
        if value is None:
            return "—"
        return "%s%%" % self._ops_short_hours(round(value, 1))

    def _ops_date_text(self, value):
        return value.strftime("%d %b %Y") if value else "—"

    def _ops_margin_tone(self, value):
        """Green > 40%, amber 20-40%, red below 20% (or negative)."""
        if value is None:
            return ""
        if value > 40:
            return "good"
        if value >= 20:
            return "warn"
        return "bad"

    def _ops_cost_domain(self, project):
        """Timesheets counted as this project's cost: those linked to the
        project's Sale Order items (matches the customer-facing cost); falls
        back to all of the project's timesheets when there is no Sale Order."""
        if project.sale_order_id:
            return [("so_line.order_id", "=", project.sale_order_id.id)]
        return [("project_id", "=", project.id)]

    def _ops_project_cost(self, project, target_currency, date):
        """Return (cost in target currency, actual hours) for the SO-linked
        timesheets; cost falls back to hours x hourly cost when it is zero."""
        company = project.company_id
        domain = self._ops_cost_domain(project)
        Line = self.env["account.analytic.line"]
        cost = 0.0
        hours = 0.0
        for row in Line.read_group(domain, ["amount:sum", "unit_amount:sum"], ["currency_id"], lazy=False):
            cur = row.get("currency_id")
            amount = row.get("amount") or 0.0
            hours += row.get("unit_amount") or 0.0
            if amount:
                source = self.env["res.currency"].browse(cur[0]) if cur else company.currency_id
                cost += abs(source._convert(amount, target_currency, company, date))
        if cost < 0.01 and hours > 0:
            raw = 0.0
            for row in Line.read_group(domain, ["unit_amount:sum"], ["employee_id"], lazy=False):
                emp = row.get("employee_id")
                if emp:
                    raw += (row.get("unit_amount") or 0.0) * (self.env["hr.employee"].browse(emp[0]).hourly_cost or 0.0)
            if raw:
                cost = abs(company.currency_id._convert(raw, target_currency, company, date))
        return cost, hours

    def _ops_project_financials(self, project, display_ccy, today):
        """SO amount, invoiced (posted + sent/paid, refunds netted), SO-linked
        cost and both margins for one project, in display_ccy."""
        order = project.sale_order_id
        if order:
            so_amount = order.currency_id._convert(
                order.amount_untaxed, display_ccy, project.company_id, today)
            # Untaxed invoiced = posted customer invoices/credit notes that
            # have been sent or paid (drafts excluded).
            invoiced = 0.0
            for move in order.invoice_ids:
                if move.state != "posted":
                    continue
                if not (move.is_move_sent or move.payment_state in (
                    "in_payment", "paid", "partial", "reversed"
                )):
                    continue
                sign = 1 if move.move_type == "out_invoice" else (-1 if move.move_type == "out_refund" else 0)
                if sign:
                    invoiced += sign * move.currency_id._convert(
                        move.amount_untaxed, display_ccy, project.company_id, today
                    )
        else:
            so_amount = 0.0
            invoiced = 0.0
        cost, actual_hours = self._ops_project_cost(project, display_ccy, today)
        # Margin = (revenue - cost) / revenue (higher is better).
        prof_so = (so_amount - cost) / so_amount * 100 if so_amount else None
        prof_inv = (invoiced - cost) / invoiced * 100 if invoiced else None
        return {
            "so_amount": so_amount,
            "invoiced": invoiced,
            "cost": cost,
            "actual_hours": actual_hours,
            "prof_so": prof_so,
            "prof_inv": prof_inv,
        }

    def _ops_week_end_dates(self, count):
        """The last `count` ISO-week Sundays, ending with this week's."""
        today = fields.Date.context_today(self)
        this_sunday = today + timedelta(days=6 - today.weekday())
        return [this_sunday - timedelta(days=7 * i) for i in range(count - 1, -1, -1)]

    def _ops_project_cost_lines(self, project, display_ccy):
        """[(date, cost in display_ccy)] per SO-linked timesheet, for rebuilding
        accumulated cost as of any past date. Mirrors _ops_project_cost's
        amount-then-hourly-fallback, decided once per project."""
        company = project.company_id
        today = fields.Date.context_today(self)
        lines = self.env["account.analytic.line"].search_read(
            self._ops_cost_domain(project),
            ["date", "amount", "currency_id", "unit_amount", "employee_id"])
        total_amount = sum(abs(line["amount"] or 0.0) for line in lines)
        use_fallback = total_amount < 0.01 and any(line["unit_amount"] for line in lines)
        rate = {}

        def to_ccy(cur_id):
            if cur_id not in rate:
                src = self.env["res.currency"].browse(cur_id) if cur_id else company.currency_id
                rate[cur_id] = src._convert(1.0, display_ccy, company, today)
            return rate[cur_id]

        out = []
        for line in lines:
            day = fields.Date.to_date(line["date"])
            if not day:
                continue
            if use_fallback:
                emp = line["employee_id"]
                hourly = self.env["hr.employee"].browse(emp[0]).hourly_cost if emp else 0.0
                amount = (line["unit_amount"] or 0.0) * hourly
                cost = abs(company.currency_id._convert(amount, display_ccy, company, today))
            else:
                cur_id = line["currency_id"][0] if line["currency_id"] else False
                cost = abs((line["amount"] or 0.0) * to_ccy(cur_id))
            out.append((day, cost))
        return out

    def _ops_invoiced_as_of(self, order, display_ccy, company, as_of):
        """Untaxed posted invoicing up to `as_of` (refunds netted). Historical
        so the sent/paid gate is dropped — invoice_date + posted is the best
        as-of proxy; cost accumulation is the dominant margin driver anyway."""
        total = 0.0
        for move in order.invoice_ids:
            if move.state != "posted":
                continue
            inv_date = move.invoice_date or move.date
            if not inv_date or inv_date > as_of:
                continue
            sign = 1 if move.move_type == "out_invoice" else (-1 if move.move_type == "out_refund" else 0)
            if sign:
                total += sign * move.currency_id._convert(
                    move.amount_untaxed, display_ccy, company, as_of)
        return total

    def _ops_project_prof_trend(self, project, display_ccy, order, so_amount,
                                cur_prof_so, cur_prof_inv):
        """Per-week (label, %margin) series for both margins; the last point is
        today's actual value, earlier points reconstructed from dated cost +
        invoicing. so_amount held at current (SOs are stable once signed)."""
        week_ends = self._ops_week_end_dates(PROF_TREND_WEEKS)
        cost_lines = self._ops_project_cost_lines(project, display_ccy)
        company = project.company_id
        so_series, inv_series = [], []
        for week_end in week_ends[:-1]:
            cost = sum(cost for day, cost in cost_lines if day <= week_end)
            prof_so = (so_amount - cost) / so_amount * 100 if so_amount else None
            invoiced = self._ops_invoiced_as_of(order, display_ccy, company, week_end) if order else 0.0
            prof_inv = (invoiced - cost) / invoiced * 100 if invoiced else None
            label = _("Wk %s") % ("%02d" % week_end.isocalendar()[1])
            so_series.append((label, prof_so))
            inv_series.append((label, prof_inv))
        current_label = _("Wk %s") % ("%02d" % week_ends[-1].isocalendar()[1])
        so_series.append((current_label, cur_prof_so))
        inv_series.append((current_label, cur_prof_inv))
        return so_series, inv_series

    def _ops_wow_text(self, series):
        """' ▼2.3' / ' ▲1.1' / '' — this week's margin vs last week (points)."""
        if len(series) < 2:
            return ""
        current, previous = series[-1][1], series[-2][1]
        if current is None or previous is None:
            return ""
        delta = current - previous
        if abs(delta) < 0.05:
            return " ▬0"
        return " %s%s" % ("▼" if delta < 0 else "▲", self._ops_short_hours(abs(delta)))

    def _ops_prof_modal(self, name, project_id, series):
        """Column-chart popup of a margin's weekly series (None weeks dropped)."""
        points = [
            {"label": label, "value": round(value, 1),
             "domain": self._json_safe([("id", "=", project_id)])}
            for label, value in series if value is not None
        ]
        return {
            "name": name,
            "help": _("Week-by-week margin %. Bars start at 0 — read the numbers."),
            "color": "#1d4ed8",
            "model": "project.project",
            "format": "percent",
            "points": points,
        }

    def _ops_project_widget(self, sub_team):
        lead_uids = self._ops_lead_user_ids(sub_team)
        lead_names = sorted({emp.user_id.name for emp in self._ops_lead_employees(sub_team) if emp.user_id})
        rows = []
        domain = []
        if lead_uids and "project.project" in self.env:
            # Nature = Internal/Support projects are delivery-irrelevant
            # here (Akshay 2026-07-06 — Support-nature projects with an
            # active stage were slipping past the STAGE exclusion). Reuses
            # the Aurika Ops rule so the two dashboards always agree.
            domain = [
                ("user_id", "in", lead_uids),
                ("stage_id.name", "not in", OPS_EXCLUDED_STAGES),
            ] + self._mgmt_nature_domain()
            projects = self.env["project.project"].search(domain, order="name")

            today = fields.Date.context_today(self)
            for project in projects:
                order = project.sale_order_id
                # Display everything in the project's registering-company currency
                # (Mrelate -> INR, Linked ERP (Pty) -> ZAR, PT Istana -> IDR).
                display_ccy = project.company_id.currency_id or project.currency_id
                fin = self._ops_project_financials(project, display_ccy, today)
                so_amount, invoiced = fin["so_amount"], fin["invoiced"]
                cost, actual_hours = fin["cost"], fin["actual_hours"]
                prof_so, prof_inv = fin["prof_so"], fin["prof_inv"]
                so_series, inv_series = self._ops_project_prof_trend(
                    project, display_ccy, order, so_amount, prof_so, prof_inv)
                rows.append({
                    "label": project.name,
                    "domain": self._json_safe([("id", "=", project.id)]),
                    "stage": project.stage_id.name or "",
                    "start": self._ops_date_text(project.date_start),
                    "end": self._ops_date_text(project.date),
                    "planned_hrs": self._ops_short_hours(project.allocated_hours),
                    "actual_hrs": self._ops_short_hours(actual_hours),
                    "so_amount": self._ops_money(so_amount, display_ccy) if order else "—",
                    "invoiced": self._ops_money(invoiced, display_ccy) if order else "—",
                    "cost": self._ops_money(cost, display_ccy),
                    "prof_so": self._ops_pct_text(prof_so) + self._ops_wow_text(so_series),
                    "prof_inv": self._ops_pct_text(prof_inv) + self._ops_wow_text(inv_series),
                    "tones": {
                        "prof_so": self._ops_margin_tone(prof_so),
                        "prof_inv": self._ops_margin_tone(prof_inv),
                    },
                    # Per-cell popups: only the two margin cells open a trend
                    # graph; every other cell falls through to the row's
                    # openRecords (unchanged).
                    "cell_modals": {
                        "prof_so": self._ops_prof_modal(
                            _("%s · % Prof (SO) trend") % project.name, project.id, so_series),
                        "prof_inv": self._ops_prof_modal(
                            _("%s · % Prof (Inv) trend") % project.name, project.id, inv_series),
                    },
                })
        managed_by = ", ".join(lead_names) if lead_names else _("no team lead mapped")
        return {
            "id": "ops_projects",
            "name": _("Project Review"),
            "type": "matrix",
            "model": "project.project",
            "mode": "computed",
            "measure": "",
            "groupby": _("Project"),
            "color": "#1d4ed8",
            "help": _("Managed by %(who)s · amounts in each project's company currency · "
                      "excludes Done / On Hold / Cancelled · margin cells show the "
                      "week-over-week change (▼ down / ▲ up) — click a margin for its "
                      "weekly trend") % {"who": managed_by},
            "value": float(len(rows)),
            "format": "integer",
            "domain": self._json_safe(domain),
            "points": [],
            "rows": rows,
            "columns": [
                {"key": "stage", "label": _("Stage"), "format": "text"},
                {"key": "start", "label": _("Start"), "format": "text"},
                {"key": "end", "label": _("Expected End"), "format": "text"},
                {"key": "planned_hrs", "label": _("Planned h (SO)"), "format": "money"},
                {"key": "actual_hrs", "label": _("Actual h"), "format": "money"},
                {"key": "so_amount", "label": _("SO Amount"), "format": "money"},
                {"key": "invoiced", "label": _("Invoiced"), "format": "money"},
                {"key": "cost", "label": _("Actual Cost"), "format": "money"},
                {"key": "prof_so", "label": _("% Prof (SO)"), "format": "money"},
                {"key": "prof_inv", "label": _("% Prof (Inv)"), "format": "money"},
            ],
            "span": 12,
            "error": False,
        }
