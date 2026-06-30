import logging
from datetime import date, datetime, time, timedelta

from pytz import utc

from odoo import fields, models, _

_logger = logging.getLogger(__name__)

OPS_DASHBOARD_NAME = "Ops Performance"

# Expected billable hours are this share of total expected hours.
BILLABLE_SHARE = 0.75

# Colour thresholds (good / warn / bad).
PASS_GOOD, PASS_WARN = 100.0, 90.0
COVERAGE_GOOD, COVERAGE_WARN = 100.0, 90.0
BILLABILITY_TARGET, BILLABILITY_WARN = 85.0, 70.0
PLANNING_TARGET, PLANNING_WARN = 85.0, 70.0

TONE_COLOR = {
    "good": "#2e7d2e",
    "warn": "#c98a1b",
    "bad": "#b03030",
    "flat": "#64748b",
}

CHART_WEEKS = 8


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
        if "account.analytic.line" not in self.env or "hr.employee" not in self.env:
            return
        self.create(
            {
                "name": OPS_DASHBOARD_NAME,
                "sequence": 30,
                "description": _(
                    "Weekly operations review: time-entry compliance, coverage, "
                    "billability, and forward planning by user."
                ),
                "color": "#1d4ed8",
            }
        )

    def _is_ops_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == OPS_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Week helpers
    # ------------------------------------------------------------------
    def _ops_anchor_date(self, date_to=False):
        if date_to:
            return fields.Date.to_date(date_to)
        return fields.Date.context_today(self)

    def _ops_week_start(self, day):
        return day - timedelta(days=day.weekday())

    def _ops_week_bounds(self, week_start):
        return week_start, week_start + timedelta(days=6)

    def _ops_week_label(self, week_start):
        return "W%02d" % week_start.isocalendar()[1]

    def _ops_weeks_back(self, last_week_start, count):
        return [last_week_start - timedelta(days=7 * i) for i in range(count - 1, -1, -1)]

    def _ops_weeks_forward(self, first_week_start, count):
        return [first_week_start + timedelta(days=7 * i) for i in range(count)]

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------
    def _ops_primary_employees(self):
        """Return {user_id: employee} for the employee in the user's default company."""
        employees = self.env["hr.employee"].search(
            [("user_id", "!=", False), ("active", "=", True)]
        )
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

    # ------------------------------------------------------------------
    # Hour aggregations
    # ------------------------------------------------------------------
    def _ops_expected_hours(self, employees, week_start, week_end):
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
            attn_days = {int(a.dayofweek) for a in calendar.attendance_ids}
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
            leave_dates = set()
            for leave in Leaves.search(leave_domain):
                lstart = fields.Datetime.to_datetime(leave.date_from).date()
                lend = fields.Datetime.to_datetime(leave.date_to).date()
                for d in work_days:
                    if lstart <= d <= lend:
                        leave_dates.add(d)
            result[emp.id] = max(0.0, (len(work_days) - len(leave_dates)) * hours_per_day)
        return result

    def _ops_timesheet_hours_by_user(self, week_start, week_end, billable_only=False):
        domain = [
            ("project_id", "!=", False),
            ("date", ">=", fields.Date.to_string(week_start)),
            ("date", "<=", fields.Date.to_string(week_end)),
        ]
        if billable_only:
            domain.append(("timesheet_invoice_type", "!=", "non_billable"))
        rows = self.env["account.analytic.line"].read_group(
            domain, ["unit_amount:sum"], ["user_id"], lazy=False
        )
        return {
            row["user_id"][0]: row.get("unit_amount", 0.0) or 0.0
            for row in rows
            if row.get("user_id")
        }

    def _ops_planned_hours_by_user(self, week_start, week_end):
        if "planning.slot" not in self.env:
            return {}
        domain = [
            ("user_id", "!=", False),
            ("start_datetime", ">=", "%s 00:00:00" % fields.Date.to_string(week_start)),
            ("start_datetime", "<=", "%s 23:59:59" % fields.Date.to_string(week_end)),
        ]
        rows = self.env["planning.slot"].read_group(
            domain, ["allocated_hours:sum"], ["user_id"], lazy=False
        )
        return {
            row["user_id"][0]: row.get("allocated_hours", 0.0) or 0.0
            for row in rows
            if row.get("user_id")
        }

    def _ops_passrate_counts_by_user(self, week_start, week_end, on_time_cutoff):
        """Return (total_by_user, ontime_by_user) entry counts for the week."""
        base = [
            ("project_id", "!=", False),
            ("date", ">=", fields.Date.to_string(week_start)),
            ("date", "<=", fields.Date.to_string(week_end)),
        ]
        Line = self.env["account.analytic.line"]
        total_rows = Line.read_group(base, ["__count"], ["user_id"], lazy=False)
        ontime_rows = Line.read_group(
            base + [("create_date", "<=", "%s 23:59:59" % fields.Date.to_string(on_time_cutoff))],
            ["__count"],
            ["user_id"],
            lazy=False,
        )
        total = {r["user_id"][0]: r.get("__count", 0) for r in total_rows if r.get("user_id")}
        ontime = {r["user_id"][0]: r.get("__count", 0) for r in ontime_rows if r.get("user_id")}
        return total, ontime

    # ------------------------------------------------------------------
    # Small maths / formatting helpers
    # ------------------------------------------------------------------
    def _ops_rate(self, numerator, denominator):
        if not denominator:
            return 0.0
        return round((numerator / denominator) * 100.0, 1)

    def _ops_tone(self, value, good, warn):
        if value >= good:
            return "good"
        if value >= warn:
            return "warn"
        return "bad"

    def _ops_delta(self, current, previous):
        diff = round(current - previous, 1)
        if diff > 0.05:
            direction, tone = "up", "good"
        elif diff < -0.05:
            direction, tone = "down", "bad"
        else:
            direction, tone = "flat", "flat"
        return {
            "value": abs(diff),
            "dir": direction,
            "tone": tone,
            "text": _("%s%% vs prior week") % self._ops_short(abs(diff)),
        }

    def _ops_short(self, value):
        value = round(value, 1)
        if value == int(value):
            return "%d" % int(value)
        return "%.1f" % value

    def _ops_timesheet_week_domain(self, week_start, week_end, user_id=False, billable_only=False):
        domain = [
            ("project_id", "!=", False),
            ("date", ">=", fields.Date.to_string(week_start)),
            ("date", "<=", fields.Date.to_string(week_end)),
        ]
        if user_id:
            domain.append(("user_id", "=", user_id))
        if billable_only:
            domain.append(("timesheet_invoice_type", "!=", "non_billable"))
        return domain

    def _ops_widget(self, wid, name, wtype, **kw):
        widget = {
            "id": wid,
            "name": name,
            "type": wtype,
            "model": kw.get("model", "account.analytic.line"),
            "mode": "computed",
            "measure": kw.get("caption", ""),
            "groupby": kw.get("groupby", ""),
            "color": kw.get("color", "#1d4ed8"),
            "help": kw.get("note", ""),
            "value": float(kw.get("value", 0) or 0),
            "format": kw.get("format", "percent"),
            "domain": self._json_safe(kw.get("domain") or []),
            "points": kw.get("points") or [],
            "rows": kw.get("rows") or [],
            "columns": kw.get("columns") or [],
            "span": kw.get("span") or False,
            "delta": kw.get("delta") or False,
            "target": kw.get("target") if kw.get("target") is not None else False,
            "badge": kw.get("badge") or "",
            "note": kw.get("note") or "",
            "error": False,
        }
        return widget

    # ------------------------------------------------------------------
    # Main payload
    # ------------------------------------------------------------------
    def _ops_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        anchor = self._ops_anchor_date(date_to)
        this_week = self._ops_week_start(anchor)
        last_week = this_week - timedelta(days=7)
        prior_week = last_week - timedelta(days=7)
        monday_this_week = this_week  # cutoff for "on time"

        bill_weeks = self._ops_weeks_back(last_week, CHART_WEEKS)
        plan_weeks = self._ops_weeks_forward(this_week, CHART_WEEKS)

        emp_map = self._ops_primary_employees()  # user_id -> employee
        employees = self.env["hr.employee"].browse([e.id for e in emp_map.values()])
        emp_by_user = {uid: emp.id for uid, emp in emp_map.items()}
        user_names = {
            u["id"]: u["name"]
            for u in self.env["res.users"].browse(list(emp_map.keys())).read(["name"])
        }

        # Expected hours per employee for every week we need.
        weeks_needed = {prior_week, last_week, this_week}
        weeks_needed.update(bill_weeks)
        weeks_needed.update(plan_weeks)
        expected_by_week = {}
        for ws in sorted(weeks_needed):
            we = ws + timedelta(days=6)
            expected_by_week[ws] = self._ops_expected_hours(employees, ws, we)

        def expected_for_user(week_start, user_id):
            return expected_by_week.get(week_start, {}).get(emp_by_user.get(user_id), 0.0)

        # Timesheet / planning aggregates per week (only the weeks each needs).
        logged_by_week = {}
        billable_by_week = {}
        for ws in sorted({prior_week, last_week} | set(bill_weeks)):
            we = ws + timedelta(days=6)
            logged_by_week[ws] = self._ops_timesheet_hours_by_user(ws, we)
            billable_by_week[ws] = self._ops_timesheet_hours_by_user(ws, we, billable_only=True)
        planned_by_week = {}
        for ws in sorted({this_week} | set(plan_weeks)):
            we = ws + timedelta(days=6)
            planned_by_week[ws] = self._ops_planned_hours_by_user(ws, we)

        last_we = last_week + timedelta(days=6)
        prior_we = prior_week + timedelta(days=6)
        this_we = this_week + timedelta(days=6)

        total_lw, ontime_lw = self._ops_passrate_counts_by_user(last_week, last_we, monday_this_week)
        total_pw, ontime_pw = self._ops_passrate_counts_by_user(prior_week, prior_we, last_week)

        # ---- Team-level cards (last completed week) ----
        user_ids = list(emp_map.keys())

        def team_rate(values_by_user, expected_week, share=1.0):
            num = sum(values_by_user.get(uid, 0.0) for uid in user_ids)
            den = sum(expected_for_user(expected_week, uid) for uid in user_ids) * share
            return self._ops_rate(num, den)

        coverage_lw = team_rate(logged_by_week.get(last_week, {}), last_week)
        coverage_pw = team_rate(logged_by_week.get(prior_week, {}), prior_week)

        pass_lw = self._ops_rate(
            sum(ontime_lw.get(uid, 0) for uid in user_ids),
            sum(total_lw.get(uid, 0) for uid in user_ids),
        )
        pass_pw = self._ops_rate(
            sum(ontime_pw.get(uid, 0) for uid in user_ids),
            sum(total_pw.get(uid, 0) for uid in user_ids),
        )

        pass_tone = self._ops_tone(pass_lw, PASS_GOOD, PASS_WARN)
        coverage_tone = self._ops_tone(coverage_lw, COVERAGE_GOOD, COVERAGE_WARN)

        # ---- DETAILS rows (one per user) ----
        detail_rows = []
        for uid in user_ids:
            exp_lw = expected_for_user(last_week, uid)
            exp_tw = expected_for_user(this_week, uid)
            logged = logged_by_week.get(last_week, {}).get(uid, 0.0)
            billable = billable_by_week.get(last_week, {}).get(uid, 0.0)
            planned = planned_by_week.get(this_week, {}).get(uid, 0.0)
            total = total_lw.get(uid, 0)
            ontime = ontime_lw.get(uid, 0)

            pass_v = self._ops_rate(ontime, total)
            coverage_v = self._ops_rate(logged, exp_lw)
            billability_v = self._ops_rate(billable, exp_lw * BILLABLE_SHARE)
            planning_v = self._ops_rate(planned, exp_tw * BILLABLE_SHARE)

            detail_rows.append(
                {
                    "label": user_names.get(uid, _("Unknown")),
                    "pass": pass_v,
                    "coverage": coverage_v,
                    "billability": billability_v,
                    "planning": planning_v,
                    "tones": {
                        "pass": self._ops_tone(pass_v, PASS_GOOD, PASS_WARN),
                        "coverage": self._ops_tone(coverage_v, COVERAGE_GOOD, COVERAGE_WARN),
                        "billability": self._ops_tone(billability_v, BILLABILITY_TARGET, BILLABILITY_WARN),
                        "planning": self._ops_tone(planning_v, PLANNING_TARGET, PLANNING_WARN),
                    },
                    "domain": self._json_safe(
                        self._ops_timesheet_week_domain(last_week, last_we, user_id=uid)
                    ),
                }
            )
        detail_rows.sort(key=lambda r: (r["billability"], r["coverage"], r["label"].lower()))

        # ---- Resource planning charts ----
        bill_points = []
        bill_vals = []
        for ws in bill_weeks:
            we = ws + timedelta(days=6)
            num = sum(billable_by_week.get(ws, {}).get(uid, 0.0) for uid in user_ids)
            den = sum(expected_for_user(ws, uid) for uid in user_ids) * BILLABLE_SHARE
            value = self._ops_rate(num, den)
            bill_vals.append(value)
            tone = self._ops_tone(value, BILLABILITY_TARGET, BILLABILITY_WARN)
            bill_points.append(
                {
                    "label": self._ops_week_label(ws),
                    "value": value,
                    "color": TONE_COLOR[tone],
                    "tone": tone,
                    "domain": self._json_safe(
                        self._ops_timesheet_week_domain(ws, we, billable_only=True)
                    ),
                }
            )

        plan_points = []
        plan_vals = []
        for ws in plan_weeks:
            we = ws + timedelta(days=6)
            num = sum(planned_by_week.get(ws, {}).get(uid, 0.0) for uid in user_ids)
            den = sum(expected_for_user(ws, uid) for uid in user_ids) * BILLABLE_SHARE
            value = self._ops_rate(num, den)
            plan_vals.append(value)
            tone = self._ops_tone(value, PLANNING_TARGET, PLANNING_WARN)
            plan_points.append(
                {
                    "label": self._ops_week_label(ws),
                    "value": value,
                    "color": TONE_COLOR[tone],
                    "tone": tone,
                    "domain": [],
                }
            )

        bill_avg = round(sum(bill_vals) / len(bill_vals), 1) if bill_vals else 0.0
        plan_avg = round(sum(plan_vals) / len(plan_vals), 1) if plan_vals else 0.0

        # ---- Assemble widgets in grid order ----
        return [
            self._ops_widget(
                "ops_sec_time_entry", _("TIME ENTRY"), "section", span=6,
                note=_("target: 100%% pass · 100%% coverage"),
            ),
            self._ops_widget(
                "ops_sec_details", _("DETAILS"), "section", span=6,
                note=_("last week — pass · coverage · billability   ·   this week — planning"),
            ),
            self._ops_widget(
                "ops_pass", _("Pass rate this week"), "kpi", span=3,
                value=pass_lw, format="percent", color=TONE_COLOR[pass_tone],
                caption=_("of last week's entries on time"),
                delta=self._ops_delta(pass_lw, pass_pw),
                domain=self._json_safe(self._ops_timesheet_week_domain(last_week, last_we)),
            ),
            self._ops_widget(
                "ops_coverage", _("Coverage this week"), "kpi", span=3,
                value=coverage_lw, format="percent", color=TONE_COLOR[coverage_tone],
                caption=_("logged vs expected hours"),
                delta=self._ops_delta(coverage_lw, coverage_pw),
                domain=self._json_safe(self._ops_timesheet_week_domain(last_week, last_we)),
            ),
            self._ops_widget(
                "ops_details", _("Details"), "matrix", span=6,
                groupby=_("Employee"), rows=detail_rows,
                columns=[
                    {"key": "pass", "label": _("% TE Pass Rate"), "format": "percent"},
                    {"key": "coverage", "label": _("% TE Coverage"), "format": "percent"},
                    {"key": "billability", "label": _("% Billability"), "format": "percent"},
                    {"key": "planning", "label": _("% Planning"), "format": "percent"},
                ],
                note=_("Sorted lowest billability first."),
            ),
            self._ops_widget(
                "ops_sec_planning", _("RESOURCE PLANNING"), "section", span=12,
                note=_("target: 85%%"),
            ),
            self._ops_widget(
                "ops_billability_chart", _("Billability — last 8 weeks"), "column", span=6,
                points=bill_points, format="percent", color="#2e7d2e",
                target=BILLABILITY_TARGET, badge=_("avg %s%%") % self._ops_short(bill_avg),
                groupby=_("Week"),
            ),
            self._ops_widget(
                "ops_planning_chart", _("Planning — next 8 weeks"), "column", span=6,
                model="planning.slot", points=plan_points, format="percent", color="#2e7d2e",
                target=PLANNING_TARGET, badge=_("avg %s%%") % self._ops_short(plan_avg),
                groupby=_("Week"),
            ),
        ]
