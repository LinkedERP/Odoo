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
        if self.with_context(active_test=False).search([("name", "=", OPS_WEEKLY_DASHBOARD_NAME)], limit=1):
            return
        if "account.analytic.line" not in self.env:
            return
        self.create(
            {
                "name": OPS_WEEKLY_DASHBOARD_NAME,
                "sequence": 50,
                "bucket": "management",
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
            try:
                selected = fields.Date.to_date(value)
            except (TypeError, ValueError):
                # Unparseable filter (stale/corrupted client value) -> YTD.
                selected = False
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
        return {"lines": 0, "late": 0, "expected": 0.0, "billable": 0.0,
                "exp_bill": 0.0, "uids": []}

    def _weekly_series(self):
        """Per-week org + per-team sums for the YTD window.

        Each weekly helper is called exactly once per week; every widget is
        derived from this single pass. Users with no squad tag count in "org"
        only. A week where a user is ineligible contributes nothing for that
        user on either side of any division.
        """
        weeks = self._weekly_ytd_weeks()
        primary_map = self._ops_primary_employees()
        exception_uids = set(self._ops_exception_user_ids(primary_map))
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
                    exp = expected.get(uid, 0.0)
                    bil = billable.get(uid, 0.0)
                    # Exception resources: expected billable = actual billable,
                    # mirroring the total-expected rule (per Akshay, 2026-07-03).
                    exp_bill = bil if uid in exception_uids else exp * BILLABLE_SHARE
                    targets = [org]
                    team_key = team_by_user.get(uid)
                    if team_key in teams:
                        targets.append(teams[team_key])
                    for rec in targets:
                        rec["lines"] += lines
                        rec["late"] += late
                        rec["expected"] += exp
                        rec["billable"] += bil
                        rec["exp_bill"] += exp_bill
                        rec["uids"].append(uid)
            by_week[week] = {"org": org, "teams": teams}
        return {"weeks": weeks, "by_week": by_week}

    def _weekly_fail_rate(self, rec):
        return round(rec["late"] / rec["lines"] * 100, 1) if rec["lines"] else 0.0

    def _weekly_bill_rate(self, rec):
        """Billable / expected billable (exception resources count their
        actual billable hours as expected billable)."""
        den = rec["exp_bill"]
        return round(rec["billable"] / den * 100, 1) if den else 0.0

    def _weekly_sum(self, recs):
        total = self._weekly_blank_rec()
        uids = set()
        for rec in recs:
            total["lines"] += rec["lines"]
            total["late"] += rec["late"]
            total["expected"] += rec["expected"]
            total["billable"] += rec["billable"]
            total["exp_bill"] += rec["exp_bill"]
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

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------
    def _weekly_fail_tone(self, rate):
        if rate < FAIL_GREEN_BELOW:
            return "good"
        if rate < FAIL_RED_FROM:
            return "warn"
        return "bad"

    def _weekly_fail_color(self, rate):
        return {"good": "#2e7d2e", "warn": "#c98a1b", "bad": "#b03030"}[
            self._weekly_fail_tone(rate)
        ]

    def _weekly_team_split_detail(self, entry, kind):
        """Hover payload for a trend point: that week's per-team split."""
        rows = []
        for key, label in self._awards_team_labels():
            rec = entry["teams"][key]
            if kind == "fail":
                cells = [
                    "%d" % rec["lines"],
                    "%d" % rec["late"],
                    self._awards_pct(self._weekly_fail_rate(rec)),
                ]
            else:
                cells = [
                    self._ops_short_hours(rec["expected"]),
                    self._ops_short_hours(rec["billable"]),
                    self._awards_pct(self._weekly_bill_rate(rec)),
                ]
            rows.append({"name": label, "cells": cells})
        org = entry["org"]
        if kind == "fail":
            cols = [_("Lines"), _("Late"), _("% Fail")]
            total_cells = [
                "%d" % org["lines"],
                "%d" % org["late"],
                self._awards_pct(self._weekly_fail_rate(org)),
            ]
        else:
            cols = [_("Expected h"), _("Billable h"), _("% Bill")]
            total_cells = [
                self._ops_short_hours(org["expected"]),
                self._ops_short_hours(org["billable"]),
                self._awards_pct(self._weekly_bill_rate(org)),
            ]
        return {
            "name_col": _("Team"),
            "cols": cols,
            "rows": rows,
            "total": {"name": _("All ops"), "cells": total_cells},
            "more": "",
        }

    def _weekly_trend_widget(self, series, selected_week):
        step = 1 if len(series["weeks"]) <= TREND_LABEL_MAX_POINTS else 2
        points = []
        for index, week in enumerate(series["weeks"]):
            entry = series["by_week"][week]
            org = entry["org"]
            points.append(
                {
                    "label": self._ops_week_num(week),
                    "week": fields.Date.to_string(week),
                    "fail": self._weekly_fail_rate(org),
                    "bill": self._weekly_bill_rate(org),
                    "show_label": index % step == 0,
                    "selected": bool(selected_week) and week == selected_week,
                    "detail_fail": self._weekly_team_split_detail(entry, "fail"),
                    "detail_bill": self._weekly_team_split_detail(entry, "bill"),
                }
            )
        widget = self._awards_base_widget(
            "weekly_trend", _("Weekly time entry trend"), "dualtrend", 12,
            _("% Fail and % Billability per week · click a week to focus the page"),
        )
        widget.update({"model": "", "points": points})
        return widget

    def _weekly_chips_widget(self, week, scope_label, teams, team_labels):
        items = []
        if week:
            items.append(
                {"icon": "fa-filter", "text": _("Showing %s") % scope_label,
                 "tone": "accent", "clear": True}
            )
        else:
            items.append(
                {"icon": "fa-calendar", "text": _("Year to date"),
                 "tone": "", "clear": False}
            )
        entered = [(key, rec) for key, rec in teams.items() if rec["lines"]]
        entered.sort(
            key=lambda item: (
                self._weekly_fail_rate(item[1]),
                team_labels.get(item[0], "").lower(),
            )
        )
        if entered:
            key, rec = entered[0]
            items.append(
                {"icon": "fa-clock-o", "tone": "good", "clear": False,
                 "text": _("Best time entry: %(team)s · %(rate)s fail") % {
                     "team": team_labels.get(key, key),
                     "rate": self._awards_pct(self._weekly_fail_rate(rec)),
                 }}
            )
        else:
            items.append(
                {"icon": "fa-clock-o", "tone": "", "clear": False,
                 "text": _("Best time entry: —")}
            )
        billed = [(key, rec) for key, rec in teams.items() if rec["expected"]]
        billed.sort(
            key=lambda item: (
                -self._weekly_bill_rate(item[1]),
                team_labels.get(item[0], "").lower(),
            )
        )
        if billed:
            key, rec = billed[0]
            items.append(
                {"icon": "fa-money", "tone": "good", "clear": False,
                 "text": _("Best billability: %(team)s · %(rate)s") % {
                     "team": team_labels.get(key, key),
                     "rate": self._awards_pct(self._weekly_bill_rate(rec)),
                 }}
            )
        else:
            items.append(
                {"icon": "fa-money", "tone": "", "clear": False,
                 "text": _("Best billability: —")}
            )
        widget = self._awards_base_widget("weekly_chips", _("Leaders"), "chips", 12)
        widget.update({"model": "", "chips": items})
        return widget

    def _weekly_bar_widgets(self, week, scope_label, teams, team_labels):
        fail_points, bill_points = [], []
        for key, label in self._awards_team_labels():
            rec = teams[key]
            frate = self._weekly_fail_rate(rec)
            brate = self._weekly_bill_rate(rec)
            fail_points.append(
                {
                    "label": label,
                    "value": frate,
                    "color": self._weekly_fail_color(frate),
                    "domain": self._json_safe(
                        self._weekly_scope_domain(week, uids=rec["uids"] or [0])
                    ),
                }
            )
            bill_points.append(
                {
                    "label": label,
                    "value": brate,
                    "color": self._ops_trend_color(brate),
                    "domain": self._json_safe(
                        self._weekly_scope_domain(
                            week, uids=rec["uids"] or [0], billable_only=True
                        )
                    ),
                }
            )
        fail_points.sort(key=lambda point: point["value"])
        bill_points.sort(key=lambda point: -point["value"])

        fail_widget = self._awards_base_widget(
            "weekly_fail_bars", _("% Fail by team"), "column", 6,
            _("%(scope)s · lower is better") % {"scope": scope_label},
        )
        fail_widget.update(
            {"measure": "%", "groupby": _("Team"), "format": "percent",
             "points": fail_points}
        )
        bill_widget = self._awards_base_widget(
            "weekly_bill_bars", _("% Billability by team"), "column", 6,
            _("%(scope)s · target %(target)s%%") % {
                "scope": scope_label,
                "target": self._ops_short_hours(WEEKLY_BILL_TARGET),
            },
        )
        bill_widget.update(
            {"measure": "%", "groupby": _("Team"), "format": "percent",
             "points": bill_points, "target": WEEKLY_BILL_TARGET}
        )
        return [fail_widget, bill_widget]

    def _weekly_table_widgets(self, week, scope_label, org, teams, team_labels):
        fail_rows, bill_rows = [], []
        for key, label in self._awards_team_labels():
            rec = teams[key]
            frate = self._weekly_fail_rate(rec)
            brate = self._weekly_bill_rate(rec)
            fail_rows.append(
                {
                    "label": label,
                    "fail": self._awards_pct(frate),
                    "failed": "{:,}".format(rec["late"]),
                    "total": "{:,}".format(rec["lines"]),
                    "sort": frate,
                    "tones": {"fail": self._weekly_fail_tone(frate)},
                    "domain": self._json_safe(
                        self._weekly_scope_domain(week, uids=rec["uids"] or [0])
                    ),
                }
            )
            bill_rows.append(
                {
                    "label": label,
                    "expected": self._ops_short_hours(rec["expected"]),
                    "actual": self._ops_short_hours(rec["billable"]),
                    "bill": self._awards_pct(brate),
                    "sort": brate,
                    "tones": {"bill": "good" if brate >= WEEKLY_BILL_TARGET else "bad"},
                    "domain": self._json_safe(
                        self._weekly_scope_domain(
                            week, uids=rec["uids"] or [0], billable_only=True
                        )
                    ),
                }
            )
        fail_rows.sort(key=lambda row: row["sort"])
        bill_rows.sort(key=lambda row: -row["sort"])
        for row in fail_rows + bill_rows:
            row.pop("sort")

        org_fail = self._weekly_fail_rate(org)
        org_bill = self._weekly_bill_rate(org)
        fail_rows.append(
            {
                "label": _("Total (all ops)"),
                "fail": self._awards_pct(org_fail),
                "failed": "{:,}".format(org["late"]),
                "total": "{:,}".format(org["lines"]),
                "tones": {},
                "domain": self._json_safe(
                    self._weekly_scope_domain(week, uids=org["uids"] or [0])
                ),
            }
        )
        bill_rows.append(
            {
                "label": _("Total (all ops)"),
                "expected": self._ops_short_hours(org["expected"]),
                "actual": self._ops_short_hours(org["billable"]),
                "bill": self._awards_pct(org_bill),
                "tones": {},
                "domain": self._json_safe(
                    self._weekly_scope_domain(
                        week, uids=org["uids"] or [0], billable_only=True
                    )
                ),
            }
        )

        fail_table = self._awards_base_widget(
            "weekly_fail_table", _("Team time entry"), "matrix", 6,
            _("%(scope)s · total includes people with no squad tag") % {
                "scope": scope_label
            },
        )
        fail_table.update(
            {
                "groupby": _("Team"),
                "compact": True,
                "rows": fail_rows,
                "columns": [
                    {"key": "fail", "label": _("% Fail"), "format": "money"},
                    {"key": "failed", "label": _("Failed"), "format": "money"},
                    {"key": "total", "label": _("Total"), "format": "money"},
                ],
            }
        )
        bill_table = self._awards_base_widget(
            "weekly_bill_table", _("Team billability"), "matrix", 6,
            _("%(scope)s · total includes people with no squad tag") % {
                "scope": scope_label
            },
        )
        bill_table.update(
            {
                "groupby": _("Team"),
                "compact": True,
                "rows": bill_rows,
                "columns": [
                    {"key": "expected", "label": _("Expected h"), "format": "money"},
                    {"key": "actual", "label": _("Actual h"), "format": "money"},
                    {"key": "bill", "label": _("% Bill."), "format": "money"},
                ],
            }
        )
        return [fail_table, bill_table]

    def _weekly_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        series = self._weekly_series()
        week = self._weekly_selected_week(filters)
        scope_label = self._weekly_scope_label(week)
        team_labels = dict(self._awards_team_labels())
        org, teams = self._weekly_scope_records(series, week)
        widgets = [self._weekly_trend_widget(series, week)]
        widgets.append(self._weekly_chips_widget(week, scope_label, teams, team_labels))
        widgets.extend(self._weekly_bar_widgets(week, scope_label, teams, team_labels))
        widgets.extend(
            self._weekly_table_widgets(week, scope_label, org, teams, team_labels)
        )
        return widgets
