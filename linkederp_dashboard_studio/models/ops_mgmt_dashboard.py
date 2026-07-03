from odoo import fields, models, _

from .ops_dashboard import OPS_EXCLUDED_STAGES, TREND_TARGET

OPS_MGMT_DASHBOARD_NAME = "Ops Management"

# Studio "Nature" selection on project.project: Support / Project / Internal.
# Internal & Support natures are excluded from all P&L views.
PROJECT_NATURE_FIELD = "x_studio_nature"
EXCLUDED_NATURES = ["Internal", "Support"]

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

    def _mgmt_selected_team(self, filters=False):
        """Validated squad value from the filters, or False for all teams."""
        filters = filters or {}
        value = filters.get("mgmt_team")
        if value and value in {v for v, _label in self._awards_team_labels()}:
            return value
        return False

    def _mgmt_filter_options(self, filters=False):
        team = self._mgmt_selected_team(filters)
        return {
            "enabled": True,
            "teams": [
                {"value": value, "label": label}
                for value, label in self._awards_team_labels()
            ],
            "team": team or "",
        }

    # ------------------------------------------------------------------
    # Monthly series (grouping the weekly org series by month)
    # ------------------------------------------------------------------
    def _mgmt_monthly_recs(self, team=False):
        """([((year, month), "Jan", rec)], ytd_rec) — weekly recs grouped by
        the month of each ISO week's Monday, CHRONOLOGICALLY (the ISO year's
        W01 can start in the previous December — that spillover sorts first
        and is labelled e.g. "Dec '25"). `team` narrows to one squad."""
        series = self._weekly_series()
        this_year = fields.Date.context_today(self).year

        def scope(week):
            entry = series["by_week"][week]
            if team:
                return entry["teams"].get(team) or self._weekly_blank_rec()
            return entry["org"]

        by_month = {}
        for week in series["weeks"]:
            by_month.setdefault((week.year, week.month), []).append(scope(week))
        monthly = []
        for key in sorted(by_month):
            year, month = key
            label = MONTH_LABELS[month - 1]
            if year != this_year:
                label = _("%(month)s '%(yy)02d") % {
                    "month": label, "yy": year % 100}
            monthly.append((key, label, self._weekly_sum(by_month[key])))
        ytd = self._weekly_sum([scope(w) for w in series["weeks"]])
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

    def _mgmt_nature_domain(self):
        Project = self.env["project.project"]
        if PROJECT_NATURE_FIELD in Project._fields:
            return [(PROJECT_NATURE_FIELD, "not in", EXCLUDED_NATURES)]
        return []

    def _mgmt_closed_projects(self, year, lead_uids=None):
        """Done projects belonging to `year`: end date year, else write_date
        year. `lead_uids` narrows to one squad's project-manager users."""
        Project = self.env["project.project"]
        domain = [("stage_id.name", "=", "Done")] + self._mgmt_nature_domain()
        if lead_uids is not None:
            domain.append(("user_id", "in", lead_uids))
        projects = Project.search(domain, order="name")
        keep = [
            p.id for p in projects
            if (p.date.year if p.date else (p.write_date and p.write_date.year)) == year
        ]
        return Project.browse(keep)

    def _mgmt_open_projects(self, lead_uids=None):
        domain = ([("stage_id.name", "not in", OPS_EXCLUDED_STAGES)]
                  + self._mgmt_nature_domain())
        if lead_uids is not None:
            domain.append(("user_id", "in", lead_uids))
        return self.env["project.project"].search(domain, order="name")

    def _mgmt_project_rows(self, projects, usd, today, closed,
                           customer_pnl=None, stats=None):
        """(rows sorted by P&L desc, total_row, total_revenue, total_cost,
        skipped_no_so). Open mode counts only SO-linked projects. When
        `customer_pnl` (a dict) is given, per-customer USD P&L + revenue
        accumulate into it. When `stats` (a dict) is given, it accumulates
        invoiced / hours (both sets) and backlog / wip (open set only)."""
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
            if stats is not None:
                stats["invoiced"] = stats.get("invoiced", 0.0) + fin["invoiced"]
                stats["hours"] = stats.get("hours", 0.0) + fin["actual_hours"]
                stats.setdefault("all_rows", []).append({
                    "id": project.id,
                    "name": project.name,
                    "company": project.company_id.name or "",
                    "invoiced": fin["invoiced"],
                    "hours": fin["actual_hours"],
                })
                if not closed:
                    stats["backlog"] = (stats.get("backlog", 0.0)
                                        + fin["so_amount"] - fin["invoiced"])
                    # WIP floors at zero per project so over-invoiced work
                    # does not offset other projects' unbilled cost.
                    stats["wip"] = (stats.get("wip", 0.0)
                                    + max(fin["cost"] - fin["invoiced"], 0.0))
                    stats.setdefault("open_rows", []).append({
                        "id": project.id,
                        "name": project.name,
                        "company": project.company_id.name or "",
                        "so_amount": fin["so_amount"],
                        "invoiced": fin["invoiced"],
                        "cost": fin["cost"],
                    })
            if customer_pnl is not None:
                partner = (project.sale_order_id.partner_id
                           if project.sale_order_id else project.partner_id)
                key = (partner.name if partner else "") or _("No customer")
                rec = customer_pnl.setdefault(
                    key, {"pnl": 0.0, "revenue": 0.0, "ids": []})
                rec["pnl"] += pnl
                rec["revenue"] += revenue
                rec["ids"].append(project.id)
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
                  modal_table=False, points=None):
        return {
            "id": wid, "name": name, "type": "kpi",
            "model": "project.project", "mode": "computed",
            "measure": caption, "groupby": "", "color": color,
            "help": help_text, "value": float(value), "format": fmt,
            # points, when given, render as a mini trend INSIDE the card.
            "domain": [], "points": points or [], "rows": [], "columns": [],
            "span": 3, "error": False,
            # Clicking the card opens this matrix in a popup instead of a
            # record list.
            "modal_table": modal_table,
        }

    def _mgmt_customer_bar(self, wid, name, entries, help_text):
        points = [{
            "label": label,
            "value": float(round(rec["pnl"])),
            # red = losing money, amber = weak positive, green = healthy
            "color": ("#dc2626" if rec["pnl"] < 0
                      else "#f59e0b" if rec["pnl"] < 1000
                      else "#059669"),
            "domain": self._json_safe([("id", "in", rec["ids"])]),
        } for label, rec in entries]
        return {
            "id": wid, "name": name, "type": "bar",
            "model": "project.project", "mode": "computed",
            "measure": _("P&L (USD)"), "groupby": _("Customer"),
            "color": "#2563eb",
            "help": help_text, "value": float(len(points)), "format": "usd",
            "domain": [], "points": points, "rows": [], "columns": [],
            "span": 6, "error": False,
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

    def _mgmt_months_table(self, wid, name, monthly, kind, help_text):
        """Popup matrix: one row per month for accuracy or billability."""
        rows = []
        for _key, label, rec in monthly:
            if kind == "accuracy":
                rate = self._mgmt_accuracy_rate(rec)
                rows.append({
                    "label": label, "domain": [],
                    "a": "%d" % rec["lines"],
                    "b": "%d" % (rec["lines"] - rec["late"]),
                    "c": self._ops_pct_text(rate),
                    "tones": {"c": "good" if rate >= ACCURACY_TARGET
                              else "warn" if rate >= ACCURACY_AMBER_FROM else "bad"},
                })
            else:
                rate = self._weekly_bill_rate(rec)
                rows.append({
                    "label": label, "domain": [],
                    "a": self._ops_short_hours(rec["billable"]),
                    "b": self._ops_short_hours(rec["exp_bill"]),
                    "c": self._ops_pct_text(rate),
                    "tones": {"c": "good" if rate >= TREND_TARGET
                              else "warn" if rate >= BILL_AMBER_FROM else "bad"},
                })
        if kind == "accuracy":
            columns = [
                {"key": "a", "label": _("Lines"), "format": "text"},
                {"key": "b", "label": _("On time"), "format": "text"},
                {"key": "c", "label": _("Accuracy"), "format": "money"},
            ]
        else:
            columns = [
                {"key": "a", "label": _("Billable h"), "format": "text"},
                {"key": "b", "label": _("Expected billable h"), "format": "text"},
                {"key": "c", "label": _("Billability"), "format": "money"},
            ]
        table = self._mgmt_matrix(wid, name, rows, columns, help_text)
        table["groupby"] = _("Month")
        return table

    def _mgmt_money_list_table(self, wid, name, entries, usd, value_key,
                               value_label, help_text):
        """Popup matrix: open projects with SO / invoiced / cost and one
        derived money column (backlog or wip), sorted by it, plus a Total."""
        entries = sorted(entries, key=lambda e: -e[value_key])
        rows = []
        total = 0.0
        for e in entries:
            total += e[value_key]
            rows.append({
                "label": e["name"],
                "domain": self._json_safe([("id", "=", e["id"])]),
                "company": e["company"],
                "so": self._ops_money(e["so_amount"], usd),
                "inv": self._ops_money(e["invoiced"], usd),
                "cost": self._ops_money(e["cost"], usd),
                "val": self._ops_money(e[value_key], usd),
                "tones": {"val": "good" if e[value_key] >= 0 else "bad"},
            })
        rows.append({
            "label": _("Total (%s projects)") % len(entries),
            "domain": [], "company": "",
            "so": "", "inv": "", "cost": "",
            "val": self._ops_money(total, usd),
            "tones": {},
        })
        return self._mgmt_matrix(wid, name, rows, [
            {"key": "company", "label": _("Company"), "format": "text"},
            {"key": "so", "label": _("SO Amount (USD)"), "format": "money"},
            {"key": "inv", "label": _("Invoiced (USD)"), "format": "money"},
            {"key": "cost", "label": _("Cost (USD)"), "format": "money"},
            {"key": "val", "label": value_label, "format": "money"},
        ], help_text)

    def _mgmt_ehr_table(self, wid, name, entries, usd, help_text):
        """Popup: effective rate per project (invoiced / hours worked)."""
        entries = [e for e in entries if e["hours"] > 0.005]
        entries.sort(key=lambda e: -(e["invoiced"] / e["hours"]))
        rows = []
        tot_inv = tot_hrs = 0.0
        for e in entries:
            rate = e["invoiced"] / e["hours"]
            tot_inv += e["invoiced"]
            tot_hrs += e["hours"]
            rows.append({
                "label": e["name"],
                "domain": self._json_safe([("id", "=", e["id"])]),
                "company": e["company"],
                "inv": self._ops_money(e["invoiced"], usd),
                "hrs": self._ops_short_hours(e["hours"]),
                "rate": self._ops_money(rate, usd),
                "tones": {},
            })
        rows.append({
            "label": _("Total (%s projects)") % len(entries),
            "domain": [], "company": "",
            "inv": self._ops_money(tot_inv, usd),
            "hrs": self._ops_short_hours(tot_hrs),
            "rate": self._ops_money(tot_inv / tot_hrs if tot_hrs else 0.0, usd),
            "tones": {},
        })
        return self._mgmt_matrix(wid, name, rows, [
            {"key": "company", "label": _("Company"), "format": "text"},
            {"key": "inv", "label": _("Invoiced (USD)"), "format": "money"},
            {"key": "hrs", "label": _("Hours"), "format": "money"},
            {"key": "rate", "label": _("USD / h"), "format": "money"},
        ], help_text)

    def _mgmt_concentration_table(self, wid, name, customer_pnl, usd, help_text):
        """Popup: revenue share per customer, biggest first."""
        entries = sorted(customer_pnl.items(),
                         key=lambda kv: -kv[1]["revenue"])
        total = sum(rec["revenue"] for _k, rec in entries) or 1.0
        rows = []
        for index, (label, rec) in enumerate(entries):
            share = rec["revenue"] / total * 100
            rows.append({
                "label": label,
                "domain": self._json_safe([("id", "in", rec["ids"])]),
                "rev": self._ops_money(rec["revenue"], usd),
                "share": self._ops_pct_text(share),
                "tones": {"share": "warn" if index < 3 else ""},
            })
        rows.append({
            "label": _("Total (%s customers)") % len(entries),
            "domain": [],
            "rev": self._ops_money(total, usd),
            "share": self._ops_pct_text(100.0),
            "tones": {},
        })
        return self._mgmt_matrix(wid, name, rows, [
            {"key": "rev", "label": _("Revenue (USD)"), "format": "money"},
            {"key": "share", "label": _("Share"), "format": "money"},
        ], help_text)

    def _mgmt_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        team = self._mgmt_selected_team(filters)
        team_label = dict(self._awards_team_labels()).get(team) if team else ""
        lead_uids = self._ops_lead_user_ids(team) if team else None
        monthly, ytd = self._mgmt_monthly_recs(team=team)
        usd = self._mgmt_usd()
        today = fields.Date.context_today(self)
        year = today.year
        usd_note = ("" if usd.name == "USD"
                    else _(" ⚠ USD not found — amounts shown in %s.") % usd.name)
        scope_note = _(" Scope: %s.") % team_label if team else ""
        project_scope_note = (
            _(" Scope: projects managed by the %s team lead.") % team_label
            if team else ""
        )

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
        customer_pnl = {}
        stats = {}
        if has_projects:
            closed_rows, closed_total, closed_rev, closed_cost, _skip = self._mgmt_project_rows(
                self._mgmt_closed_projects(year, lead_uids=lead_uids), usd, today,
                closed=True, customer_pnl=customer_pnl, stats=stats)
            open_rows, open_total, open_rev, open_cost, skipped = self._mgmt_project_rows(
                self._mgmt_open_projects(lead_uids=lead_uids), usd, today,
                closed=False, customer_pnl=customer_pnl, stats=stats)
        else:
            closed_rows, closed_total, closed_rev, closed_cost = [], {}, 0.0, 0.0
            open_rows, open_total, open_rev, open_cost, skipped = [], {}, 0.0, 0.0, 0

        closed_pnl = closed_rev - closed_cost
        closed_prof = (closed_pnl / closed_rev * 100) if closed_rev else None
        open_pnl = open_rev - open_cost

        closed_matrix = open_matrix = False
        if has_projects:
            closed_matrix = self._mgmt_matrix(
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
                _("Amounts in USD at today's rates.%(scope)s%(note)s")
                % {"scope": project_scope_note, "note": usd_note})
            open_matrix = self._mgmt_matrix(
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
                  "USD at today's rates.%(scope)s%(note)s")
                % {"skip": skipped, "scope": project_scope_note,
                   "note": usd_note})

        pass_rule = _("A line is on time if entered by 23:59 of the Monday "
                      "after its week. Delivery team, eligibility rules as "
                      "on the ops dashboards.")

        widgets = [
            self._mgmt_kpi(
                "mgmt_accuracy", _("Time Entry Accuracy (YTD)"), accuracy, "percent",
                _("%(on)s of %(lines)s lines on time") % {
                    "on": ytd["lines"] - ytd["late"], "lines": ytd["lines"]},
                "#2563eb", pass_rule + scope_note
                + _(" Click to see the month-by-month table."),
                points=acc_points,
                modal_table=self._mgmt_months_table(
                    "mgmt_accuracy_months", _("Time Entry Accuracy by Month"),
                    monthly, "accuracy", pass_rule + scope_note)),
            self._mgmt_kpi(
                "mgmt_billability", _("Billability (YTD)"), billability, "percent",
                _("%(bill)s of %(exp)s expected billable h") % {
                    "bill": self._ops_short_hours(ytd["billable"]),
                    "exp": self._ops_short_hours(ytd["exp_bill"])},
                "#059669",
                _("Billable hours vs expected billable (75%% of expected hours; "
                  "exception resources count actual as expected).") + scope_note
                + _(" Click to see the month-by-month table."),
                points=bil_points,
                modal_table=self._mgmt_months_table(
                    "mgmt_billability_months", _("Billability by Month"),
                    monthly, "billability",
                    _("Billable vs expected billable per month.") + scope_note)),
            self._mgmt_kpi(
                "mgmt_closed_pnl", _("Closed Project P&L (USD)"), closed_pnl, "usd",
                _("%(prof)s profitability · %(n)s projects") % {
                    "prof": self._ops_pct_text(closed_prof), "n": len(closed_rows)},
                "#7c3aed",
                _("Done projects with %(year)s end date (no end date: last "
                  "modified %(year)s), excluding Internal/Support nature: "
                  "invoiced minus actual cost. Click to open the project "
                  "table.%(scope)s%(note)s")
                % {"year": year, "scope": project_scope_note, "note": usd_note},
                modal_table=closed_matrix),
            self._mgmt_kpi(
                "mgmt_open_pnl", _("Open Project P&L (USD)"), open_pnl, "usd",
                _("%(n)s projects · %(skip)s without SO skipped") % {
                    "n": len(open_rows), "skip": skipped},
                "#db2777",
                _("Projects not Done / On Hold / Cancelled (stage), excluding "
                  "Internal/Support nature, with a Sale Order: SO amount "
                  "minus actual cost to date. Click to open the project "
                  "table.%(scope)s%(note)s")
                % {"scope": project_scope_note, "note": usd_note},
                modal_table=open_matrix),
        ]
        if has_projects:
            ranked = sorted(customer_pnl.items(),
                            key=lambda kv: kv[1]["pnl"], reverse=True)
            top5 = [(k, v) for k, v in ranked if v["pnl"] > 0][:5]
            top_keys = {k for k, _v in top5}
            bottom5 = sorted(
                [(k, v) for k, v in ranked if k not in top_keys],
                key=lambda kv: kv[1]["pnl"])[:5]
            customer_note = _(
                "Customer P&L across the closed-%(year)s and open projects "
                "above (invoiced/SO amount minus cost, USD)."
            ) % {"year": year}

            # Money-in-the-tank and efficiency measures over the same
            # project sets (nature/team scoping inherited).
            backlog = stats.get("backlog", 0.0)
            wip = stats.get("wip", 0.0)
            invoiced_all = stats.get("invoiced", 0.0)
            hours_all = stats.get("hours", 0.0)
            ehr = invoiced_all / hours_all if hours_all else 0.0
            revenues = sorted((rec["revenue"] for rec in customer_pnl.values()),
                              reverse=True)
            total_revenue = sum(revenues)
            top3_revenue = sum(revenues[:3])
            concentration = (top3_revenue / total_revenue * 100
                             if total_revenue else 0.0)
            top3_names = [k for k, _v in sorted(
                customer_pnl.items(), key=lambda kv: -kv[1]["revenue"])[:3]]
            # Layout: 2x2 KPI block on the left, customer charts stacked on
            # the right — [backlog, wip, top5(6)] then [conc, ehr, bottom5(6)].
            widgets += [
                self._mgmt_kpi(
                    "mgmt_backlog", _("Backlog (USD)"), backlog, "usd",
                    _("sold, not yet invoiced · %s open projects") % len(open_rows),
                    "#2563eb",
                    _("Open SO-linked projects: SO amount minus invoiced — "
                      "work already sold that still has to be delivered and "
                      "billed. Click for the per-project list.%(scope)s%(note)s")
                    % {"scope": project_scope_note, "note": usd_note},
                    modal_table=self._mgmt_money_list_table(
                        "mgmt_backlog_projects", _("Backlog by Project (USD)"),
                        [dict(e, backlog=e["so_amount"] - e["invoiced"])
                         for e in stats.get("open_rows", [])],
                        usd, "backlog", _("Backlog (USD)"),
                        _("SO amount minus invoiced per open project."
                          "%(scope)s%(note)s")
                        % {"scope": project_scope_note, "note": usd_note})),
                self._mgmt_kpi(
                    "mgmt_wip", _("Unbilled Work / WIP (USD)"), wip, "usd",
                    _("cost burned, awaiting invoicing"),
                    "#b45309",
                    _("Open projects where cost to date exceeds what has been "
                      "invoiced (floored at zero per project) — money spent "
                      "that is not yet billed. Click for the per-project "
                      "list.%(scope)s%(note)s")
                    % {"scope": project_scope_note, "note": usd_note},
                    modal_table=self._mgmt_money_list_table(
                        "mgmt_wip_projects", _("Unbilled Work by Project (USD)"),
                        [dict(e, wip=e["cost"] - e["invoiced"])
                         for e in stats.get("open_rows", [])
                         if e["cost"] - e["invoiced"] > 0.005],
                        usd, "wip", _("Unbilled (USD)"),
                        _("Cost to date minus invoiced, per open project with "
                          "unbilled cost.%(scope)s%(note)s")
                        % {"scope": project_scope_note, "note": usd_note})),
                self._mgmt_customer_bar(
                    "mgmt_top_profit_customers",
                    _("Top 5 Profitable Customers (USD)"), top5,
                    customer_note + project_scope_note + usd_note),
                self._mgmt_kpi(
                    "mgmt_concentration", _("Customer Concentration"),
                    round(concentration, 1), "percent",
                    _("top 3 of %(n)s customers: %(names)s") % {
                        "n": len(customer_pnl),
                        "names": ", ".join(top3_names) or "—"},
                    "#7c3aed",
                    _("Share of total revenue (invoiced + SO) held by the "
                      "three biggest customers — dependency risk. Click for "
                      "the revenue share per customer.%(scope)s%(note)s")
                    % {"scope": project_scope_note, "note": usd_note},
                    modal_table=self._mgmt_concentration_table(
                        "mgmt_concentration_customers",
                        _("Revenue Share by Customer (USD)"), customer_pnl, usd,
                        _("Invoiced + SO revenue per customer; the top 3 "
                          "(highlighted) drive the concentration KPI."
                          "%(scope)s%(note)s")
                        % {"scope": project_scope_note, "note": usd_note})),
                self._mgmt_kpi(
                    "mgmt_ehr", _("Effective Hourly Rate"),
                    ehr, "usd",
                    _("%(inv)s invoiced / %(hrs)s h worked") % {
                        "inv": self._ops_money(invoiced_all, usd),
                        "hrs": self._ops_short_hours(hours_all)},
                    "#059669",
                    _("Invoiced USD across all projects in scope divided by "
                      "the hours worked on them — what an hour of our work "
                      "actually earns. Click for the rate per project."
                      "%(scope)s%(note)s")
                    % {"scope": project_scope_note, "note": usd_note},
                    modal_table=self._mgmt_ehr_table(
                        "mgmt_ehr_projects",
                        _("Effective Hourly Rate by Project (USD)"),
                        stats.get("all_rows", []), usd,
                        _("Invoiced divided by hours worked, per project "
                          "(projects with no hours excluded).%(scope)s%(note)s")
                        % {"scope": project_scope_note, "note": usd_note})),
                self._mgmt_customer_bar(
                    "mgmt_bottom_customers",
                    _("Bottom 5 Customers (USD)"), bottom5,
                    _("The weakest customer relationships in scope — red is "
                      "losing money, amber is barely profitable. ")
                    + customer_note + project_scope_note + usd_note),
            ]
        return widgets
