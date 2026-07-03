from odoo import fields, models, _

from .ops_dashboard import OPS_EXCLUDED_STAGES, TREND_TARGET

OPS_MGMT_DASHBOARD_NAME = "Ops Management"

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Accuracy tones: green at/above 90, amber 80-90, red below 80.
ACCURACY_TARGET = 90.0
ACCURACY_AMBER_FROM = 80.0
# Billability tones: green at/above the 75% target, amber from 60.
BILL_AMBER_FROM = 60.0


class LinkederpDashboardOpsMgmt(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_mgmt_dashboard()

    def _ensure_mgmt_dashboard(self):
        if self.with_context(active_test=False).search([("name", "=", OPS_MGMT_DASHBOARD_NAME)], limit=1):
            return
        if "account.analytic.line" not in self.env:
            return
        self.create(
            {
                "name": OPS_MGMT_DASHBOARD_NAME,
                "sequence": 60,
                "bucket": "management",
                "description": _(
                    "Management year-to-date view: time-entry accuracy, "
                    "billability, and project P&L in USD."
                ),
                "color": "#1d4ed8",
            }
        )

    def _is_mgmt_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == OPS_MGMT_DASHBOARD_NAME.lower()

    def _mgmt_filter_options(self, filters=False):
        # No controls; the flag only hides the generic date inputs.
        return {"enabled": True}

    # ------------------------------------------------------------------
    # Monthly series (grouping the weekly org series by month)
    # ------------------------------------------------------------------
    def _mgmt_monthly_recs(self):
        """([(month, "Jan", rec)], ytd_rec) — weekly org recs grouped by the
        month of each ISO week's Monday; YTD = sum over all YTD weeks."""
        series = self._weekly_series()
        by_month = {}
        for week in series["weeks"]:
            by_month.setdefault(week.month, []).append(series["by_week"][week]["org"])
        monthly = [
            (month, MONTH_LABELS[month - 1], self._weekly_sum(by_month[month]))
            for month in sorted(by_month)
        ]
        ytd = self._weekly_sum([series["by_week"][w]["org"] for w in series["weeks"]])
        return monthly, ytd

    def _mgmt_accuracy_rate(self, rec):
        """On-time share of project timesheet lines (100 - % fail)."""
        if not rec["lines"]:
            return 0.0
        return round((rec["lines"] - rec["late"]) / rec["lines"] * 100, 1)

    def _mgmt_tone_color(self, value, green_from, amber_from):
        if value >= green_from:
            return "#2e7d2e"
        if value >= amber_from:
            return "#b45309"
        return "#b03030"

    # ------------------------------------------------------------------
    # Money (all USD)
    # ------------------------------------------------------------------
    def _mgmt_usd(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        if not usd:
            usd = self.env["res.currency"].with_context(active_test=False).search(
                [("name", "=", "USD")], limit=1)
        return usd or self.env.company.currency_id

    def _mgmt_closed_projects(self, year):
        """Done projects belonging to `year`: end date year, else write_date year."""
        Project = self.env["project.project"]
        projects = Project.search([("stage_id.name", "=", "Done")], order="name")
        keep = [
            p.id for p in projects
            if (p.date.year if p.date else (p.write_date and p.write_date.year)) == year
        ]
        return Project.browse(keep)

    def _mgmt_open_projects(self):
        return self.env["project.project"].search(
            [("stage_id.name", "not in", OPS_EXCLUDED_STAGES)], order="name")

    def _mgmt_project_rows(self, projects, usd, today, closed):
        """(rows sorted by P&L desc, total_row, total_revenue, total_cost,
        skipped_no_so). Open mode counts only SO-linked projects."""
        rows, tot_rev, tot_cost, skipped = [], 0.0, 0.0, 0
        for project in projects:
            if not closed and not project.sale_order_id:
                skipped += 1
                continue
            fin = self._ops_project_financials(project, usd, today)
            revenue = fin["invoiced"] if closed else fin["so_amount"]
            pnl = revenue - fin["cost"]
            prof = fin["prof_inv"] if closed else fin["prof_so"]
            tot_rev += revenue
            tot_cost += fin["cost"]
            row = {
                "label": project.name,
                "domain": self._json_safe([("id", "=", project.id)]),
                "company": project.company_id.name or "",
                "revenue": self._ops_money(revenue, usd),
                "cost": self._ops_money(fin["cost"], usd),
                "pnl": self._ops_money(pnl, usd),
                "prof": self._ops_pct_text(prof),
                "tones": {
                    "prof": self._ops_margin_tone(prof),
                    "pnl": "good" if pnl >= 0 else "bad",
                },
                "_pnl": pnl,
            }
            if closed:
                row["end"] = self._ops_date_text(project.date)
            else:
                row["stage"] = project.stage_id.name or ""
            rows.append(row)
        rows.sort(key=lambda r: r["_pnl"], reverse=True)
        for row in rows:
            row.pop("_pnl")
        total_prof = (tot_rev - tot_cost) / tot_rev * 100 if tot_rev else None
        total_row = {
            "label": _("Total (%s projects)") % len(rows),
            "domain": [],
            "company": "",
            "revenue": self._ops_money(tot_rev, usd),
            "cost": self._ops_money(tot_cost, usd),
            "pnl": self._ops_money(tot_rev - tot_cost, usd),
            "prof": self._ops_pct_text(total_prof),
            "tones": {"prof": self._ops_margin_tone(total_prof)},
        }
        if closed:
            total_row["end"] = ""
        else:
            total_row["stage"] = ""
        return rows, total_row, tot_rev, tot_cost, skipped

    # ------------------------------------------------------------------
    # Widget builders
    # ------------------------------------------------------------------
    def _mgmt_kpi(self, wid, name, value, fmt, caption, color, help_text,
                  jump_to=False):
        return {
            "id": wid, "name": name, "type": "kpi",
            "model": "project.project", "mode": "computed",
            "measure": caption, "groupby": "", "color": color,
            "help": help_text, "value": float(value), "format": fmt,
            "domain": [], "points": [], "rows": [], "columns": [],
            "span": 3, "error": False,
            # Clicking the card scrolls to this widget id instead of opening
            # a record list.
            "jump_to": jump_to,
        }

    def _mgmt_trend(self, wid, name, points, target, help_text):
        values = [p["value"] for p in points]
        avg = round(sum(values) / len(values), 1) if values else 0.0
        return {
            "id": wid, "name": name, "type": "column",
            "model": "account.analytic.line", "mode": "computed",
            "measure": "%", "groupby": _("Month"), "color": "#2e7d2e",
            "help": help_text, "value": float(values[-1] if values else 0.0),
            "format": "percent", "domain": [], "points": points,
            "rows": [], "columns": [], "span": 6, "error": False,
            "badge": _("avg %s%%") % self._ops_short_hours(avg),
            "target": target,
        }

    def _mgmt_matrix(self, wid, name, rows, columns, help_text):
        return {
            "id": wid, "name": name, "type": "matrix",
            "model": "project.project", "mode": "computed",
            "measure": "", "groupby": _("Project"), "color": "#1d4ed8",
            "help": help_text, "value": float(max(len(rows) - 1, 0)),
            "format": "integer", "domain": [], "points": [],
            "rows": rows, "columns": columns, "span": 12, "error": False,
        }

    def _mgmt_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        monthly, ytd = self._mgmt_monthly_recs()
        usd = self._mgmt_usd()
        today = fields.Date.context_today(self)
        year = today.year
        usd_note = ("" if usd.name == "USD"
                    else _(" ⚠ USD not found — amounts shown in %s.") % usd.name)

        accuracy = self._mgmt_accuracy_rate(ytd)
        billability = self._weekly_bill_rate(ytd)

        acc_points = []
        bil_points = []
        for _month, label, rec in monthly:
            acc_value = self._mgmt_accuracy_rate(rec)
            bil_value = self._weekly_bill_rate(rec)
            acc_points.append({
                "label": label, "value": acc_value,
                "color": self._mgmt_tone_color(acc_value, ACCURACY_TARGET, ACCURACY_AMBER_FROM),
                "domain": [], "detail": None,
            })
            bil_points.append({
                "label": label, "value": bil_value,
                "color": self._mgmt_tone_color(bil_value, TREND_TARGET, BILL_AMBER_FROM),
                "domain": [], "detail": None,
            })

        has_projects = "project.project" in self.env and "sale.order" in self.env
        if has_projects:
            closed_rows, closed_total, closed_rev, closed_cost, _skip = self._mgmt_project_rows(
                self._mgmt_closed_projects(year), usd, today, closed=True)
            open_rows, open_total, open_rev, open_cost, skipped = self._mgmt_project_rows(
                self._mgmt_open_projects(), usd, today, closed=False)
        else:
            closed_rows, closed_total, closed_rev, closed_cost = [], {}, 0.0, 0.0
            open_rows, open_total, open_rev, open_cost, skipped = [], {}, 0.0, 0.0, 0

        closed_pnl = closed_rev - closed_cost
        closed_prof = (closed_pnl / closed_rev * 100) if closed_rev else None
        open_pnl = open_rev - open_cost

        pass_rule = _("A line is on time if entered by 23:59 of the Monday "
                      "after its week. Delivery team, eligibility rules as "
                      "on the ops dashboards.")

        widgets = [
            self._mgmt_kpi(
                "mgmt_accuracy", _("Time Entry Accuracy (YTD)"), accuracy, "percent",
                _("%(on)s of %(lines)s lines on time") % {
                    "on": ytd["lines"] - ytd["late"], "lines": ytd["lines"]},
                "#2563eb", pass_rule),
            self._mgmt_kpi(
                "mgmt_billability", _("Billability (YTD)"), billability, "percent",
                _("%(bill)s of %(exp)s expected billable h") % {
                    "bill": self._ops_short_hours(ytd["billable"]),
                    "exp": self._ops_short_hours(ytd["exp_bill"])},
                "#059669",
                _("Billable hours vs expected billable (75%% of expected hours; "
                  "exception resources count actual as expected).")),
            self._mgmt_kpi(
                "mgmt_closed_pnl", _("Closed Project P&L (USD)"), closed_pnl, "usd",
                _("%(prof)s profitability · %(n)s projects") % {
                    "prof": self._ops_pct_text(closed_prof), "n": len(closed_rows)},
                "#7c3aed",
                _("Done projects with %(year)s end date (no end date: last "
                  "modified %(year)s): invoiced minus actual cost. Click to "
                  "see the project table.%(note)s")
                % {"year": year, "note": usd_note},
                jump_to="mgmt_closed_projects"),
            self._mgmt_kpi(
                "mgmt_open_pnl", _("Open Project P&L (USD)"), open_pnl, "usd",
                _("%(n)s projects · %(skip)s without SO skipped") % {
                    "n": len(open_rows), "skip": skipped},
                "#db2777",
                _("Projects not Done / On Hold / Cancelled / Internal / "
                  "Support, with a Sale Order: SO amount minus actual cost "
                  "to date. Click to see the project table.%(note)s")
                % {"note": usd_note},
                jump_to="mgmt_open_projects"),
            self._mgmt_trend(
                "mgmt_accuracy_trend", _("Accuracy by Month"), acc_points,
                ACCURACY_TARGET,
                _("On-time share per month (weeks grouped by their Monday). "
                  "Dotted line = %s%%.") % self._ops_short_hours(ACCURACY_TARGET)),
            self._mgmt_trend(
                "mgmt_billability_trend", _("Billability by Month"), bil_points,
                TREND_TARGET,
                _("Billable vs expected billable per month. Dotted line = "
                  "%s%%.") % self._ops_short_hours(TREND_TARGET)),
        ]
        if has_projects:
            widgets.append(self._mgmt_matrix(
                "mgmt_closed_projects", _("Closed Projects %s (P&L)") % year,
                closed_rows + [closed_total],
                [
                    {"key": "company", "label": _("Company"), "format": "text"},
                    {"key": "end", "label": _("End"), "format": "text"},
                    {"key": "revenue", "label": _("Invoiced (USD)"), "format": "money"},
                    {"key": "cost", "label": _("Actual Cost (USD)"), "format": "money"},
                    {"key": "pnl", "label": _("P&L (USD)"), "format": "money"},
                    {"key": "prof", "label": _("% Prof (Inv)"), "format": "money"},
                ],
                _("Amounts in USD at today's rates.%s") % usd_note))
            widgets.append(self._mgmt_matrix(
                "mgmt_open_projects", _("Open Projects (P&L to date)"),
                open_rows + [open_total],
                [
                    {"key": "company", "label": _("Company"), "format": "text"},
                    {"key": "stage", "label": _("Stage"), "format": "text"},
                    {"key": "revenue", "label": _("SO Amount (USD)"), "format": "money"},
                    {"key": "cost", "label": _("Actual Cost (USD)"), "format": "money"},
                    {"key": "pnl", "label": _("P&L (USD)"), "format": "money"},
                    {"key": "prof", "label": _("% Prof (SO)"), "format": "money"},
                ],
                _("Excludes Done / On Hold / Cancelled / Internal / Support; "
                  "%(skip)s projects without a Sale Order skipped. Amounts in "
                  "USD at today's rates.%(note)s")
                % {"skip": skipped, "note": usd_note}))
        return widgets
