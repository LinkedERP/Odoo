from odoo import fields, models, _

SALES_DASHBOARD_NAME = "Sales Performance Dashboard"

# ---------------------------------------------------------------------------
# Linked BD Pipeline Strength Scoring (deck of 2026; the matrix screenshots
# are authoritative where the slide text disagrees).
# ---------------------------------------------------------------------------
SALES_STAGE_ORDER = ["attract", "engage", "advise", "align", "persuade"]
SALES_STAGE_LABELS = {
    "attract": "Attract",
    "engage": "Engage",
    "advise": "Advise",
    "align": "Align",
    "persuade": "Persuade",
}
SALES_STAGE_POINTS = {"attract": 1, "engage": 2, "advise": 3, "align": 4, "persuade": 5}
# Strength denominator: the maximum a deal of that stage can score
# (Timing/Probability are locked before Align, so early stages max lower).
SALES_MAX_POINTS = {"attract": 7, "engage": 9, "advise": 11, "align": 23, "persuade": 25}
# Age buckets (days): 0-15 / 16-30 / 31-45 / 46-60 / 61-90 / 91-120 / 121-150 / >150
SALES_AGE_EDGES = (15, 30, 45, 60, 90, 120, 150)
SALES_VELOCITY = {
    "attract": (1, 0, 0, 0, 0, 0, 0, 0),
    "engage": (2, 2, 1, 1, 0, 0, 0, 0),
    "advise": (3, 3, 3, 2, 2, 1, 0, 0),
    "align": (4, 4, 4, 4, 3, 2, 1, 0),
    "persuade": (5, 5, 5, 5, 5, 3, 2, 1),
}
# Timing (Align/Persuade only): days until the expected close date.
# Overdue or missing = 0 points + hygiene flag (Akshay, 2026-07-04).
SALES_TIMING_ROW = (5, 5, 4, 3, 2, 1, 1, 1)
# Value bands (USD, first-year editor ARR = expected_revenue): the two rulers.
SALES_NS_BANDS = (10000.0, 20000.0, 30000.0, 40000.0)
SALES_OD_BANDS = (2500.0, 5000.0, 7500.0, 10000.0)
# Probability bands (Align/Persuade only): <=25 / <=50 / <=70 / <=90 / >90.
SALES_PROB_EDGES = ((25.0, 1), (50.0, 2), (70.0, 3), (90.0, 4))

SALES_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# SCA milestone date fields (Studio); each is skipped gracefully if absent.
SALES_MILESTONES = [
    ("x_studio_intro", "Intro"),
    ("x_studio_discovery", "Discovery"),
    ("x_studio_demo", "Demo"),
    ("x_studio_proposal", "Proposal"),
    ("x_studio_alignment", "Alignment"),
    ("x_studio_selection", "Selection"),
]

STRENGTH_GOOD_FROM = 60.0
STRENGTH_WARN_FROM = 40.0


class LinkederpDashboardSales(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_sales_dashboard()

    def _ensure_sales_dashboard(self):
        if self._ensure_dashboard_name(SALES_DASHBOARD_NAME, []):
            return
        if "crm.lead" not in self.env:
            return
        self.create(
            {
                "name": SALES_DASHBOARD_NAME,
                "sequence": 15,
                "bucket": "sales",
                "description": _(
                    "BD pipeline strength (Stage · Velocity · Value · Timing "
                    "· Probability): every open deal scored against its "
                    "stage's maximum, all money in USD."
                ),
                "color": "#2563eb",
            }
        )

    def _is_sales_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == SALES_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Filters (year + salesperson + company single, sales teams MULTI)
    # ------------------------------------------------------------------
    def _sales_years(self):
        current = fields.Date.context_today(self).year
        return [current, current - 1, current - 2]

    def _sales_selected(self, filters=False):
        """Validated filter values; garbage falls back to the defaults."""
        filters = filters or {}
        years = self._sales_years()
        try:
            year = int(filters.get("sales_year") or 0)
        except (TypeError, ValueError):
            year = 0
        if year not in years:
            year = years[0]

        def valid_id(value, options):
            try:
                value = int(value or 0)
            except (TypeError, ValueError):
                return False
            return value if value in options else False

        person_ids = {o["id"] for o in self._sales_person_options()}
        company_ids = set(self.env["res.company"].search([]).ids)
        team_ids = {o["id"] for o in self._sales_team_options()}
        person = valid_id(filters.get("sales_person_id"), person_ids)
        company = valid_id(filters.get("sales_company_id"), company_ids)
        raw_teams = filters.get("sales_team_ids") or []
        if not isinstance(raw_teams, (list, tuple)):
            raw_teams = []
        teams = []
        for value in raw_teams:
            team = valid_id(value, team_ids)
            if team and team not in teams:
                teams.append(team)
        return {"year": year, "person": person, "company": company, "teams": teams}

    def _sales_person_options(self):
        return self._crm_filter_options_for_field(
            [("type", "=", "opportunity")], "user_id")

    def _sales_team_options(self):
        return self._crm_filter_options_for_field(
            [("type", "=", "opportunity")], "team_id")

    def _sales_filter_options(self, filters=False):
        selected = self._sales_selected(filters)
        return {
            "enabled": True,
            "year": selected["year"],
            "years": [{"value": y, "label": str(y)} for y in self._sales_years()],
            "salesperson": selected["person"] or "",
            "salespersons": self._sales_person_options(),
            "company": selected["company"] or "",
            "companies": [
                {"id": company.id, "name": company.name}
                for company in self.env["res.company"].search([])
            ],
            "team_ids": selected["teams"],
            "teams": self._sales_team_options(),
        }

    # ------------------------------------------------------------------
    # Scoring primitives
    # ------------------------------------------------------------------
    def _sales_stage_key(self, stage_name):
        name = (stage_name or "").lower()
        for key in SALES_STAGE_ORDER:
            if key in name:
                return key
        return None

    def _sales_age_bucket(self, days):
        for index, edge in enumerate(SALES_AGE_EDGES):
            if days <= edge:
                return index
        return len(SALES_AGE_EDGES)

    def _sales_value_score(self, usd, ruler):
        if usd <= 0:
            return 0
        bands = SALES_OD_BANDS if ruler == "odoo" else SALES_NS_BANDS
        for index, edge in enumerate(bands):
            if usd <= edge:
                return index + 1
        return 5

    def _sales_prob_score(self, probability):
        for edge, score in SALES_PROB_EDGES:
            if probability <= edge:
                return score
        return 5

    def _sales_strength_tone(self, pct):
        if pct >= STRENGTH_GOOD_FROM:
            return "good"
        if pct >= STRENGTH_WARN_FROM:
            return "warn"
        return "bad"

    # ------------------------------------------------------------------
    # Data collection (one pass over the CRM)
    # ------------------------------------------------------------------
    def _sales_base_domain(self, selected):
        domain = [("type", "=", "opportunity")]
        if selected["person"]:
            domain.append(("user_id", "=", selected["person"]))
        if selected["company"]:
            domain.append(("company_id", "=", selected["company"]))
        if selected["teams"]:
            domain.append(("team_id", "in", selected["teams"]))
        return domain

    def _sales_usd_factor_map(self, usd, today):
        """currency id -> multiplier into USD (newest stored rates)."""
        factors = {}

        def factor(currency, company):
            key = (currency.id, company.id)
            if key not in factors:
                factors[key] = currency._convert(
                    1.0, usd, company, today, round=False)
            return factors[key]

        return factor

    def _sales_collect(self, selected):
        """Score the active pipeline and split the selected year's closed
        deals into won / lost — all money in USD at newest stored rates."""
        Lead = self.env["crm.lead"].with_context(active_test=False)
        usd = self._mgmt_usd()
        today = fields.Date.context_today(self)
        year = selected["year"]
        factor = self._sales_usd_factor_map(usd, today)
        tag_names = {tag.id: (tag.name or "").lower()
                     for tag in self.env["crm.tag"].search([])}
        milestone_fields = [
            (field, label) for field, label in SALES_MILESTONES
            if field in Lead._fields
        ]

        deals, won, lost = [], [], []
        leads = Lead.search(self._sales_base_domain(selected))
        for lead in leads:
            currency = lead.company_currency or usd
            company = lead.company_id or self.env.company
            usd_amount = (lead.expected_revenue or 0.0) * factor(currency, company)
            closed = lead.date_closed and lead.date_closed.date()
            is_won = lead.won_status == "won"
            # An archived deal at probability 100 is an archived WIN, not a
            # loss — keep it out of the lost list (and the win rate).
            is_lost = (lead.won_status == "lost"
                       or (not lead.active and not is_won
                           and (lead.probability or 0.0) < 100.0))

            if is_won:
                if closed and closed.year == year:
                    cycle = (closed - lead.create_date.date()).days if lead.create_date else None
                    won.append({
                        "id": lead.id, "name": lead.name or "?",
                        "user": lead.user_id.name or _("Unassigned"),
                        "usd": usd_amount, "closed": closed,
                        "month": closed.month, "cycle": cycle,
                    })
                continue
            if is_lost:
                lost_year = closed.year if closed else (
                    lead.write_date and lead.write_date.year)
                if lost_year == year:
                    lost.append({
                        "id": lead.id, "name": lead.name or "?",
                        "usd": usd_amount,
                        "reason": lead.lost_reason_id.name or _("(no reason)"),
                    })
                continue
            if not lead.active:
                continue

            stage_key = self._sales_stage_key(lead.stage_id.name)
            if not stage_key:
                continue

            ruler = None
            for tag_id in lead.tag_ids.ids:
                tag = tag_names.get(tag_id, "")
                if "netsuite" in tag:
                    ruler = "netsuite"
                    break
                if "odoo" in tag:
                    ruler = ruler or "odoo"

            age = (today - lead.create_date.date()).days if lead.create_date else 0
            s_stage = SALES_STAGE_POINTS[stage_key]
            s_velocity = SALES_VELOCITY[stage_key][self._sales_age_bucket(age)]
            s_value = self._sales_value_score(usd_amount, ruler or "netsuite")
            s_timing = s_prob = 0
            flags = set()
            deadline = lead.date_deadline
            late_stage = stage_key in ("align", "persuade")
            if late_stage:
                if not deadline:
                    flags.add("no_deadline")
                elif (deadline - today).days < 0:
                    flags.add("overdue")
                else:
                    s_timing = SALES_TIMING_ROW[
                        self._sales_age_bucket((deadline - today).days)]
                if lead.is_automated_probability:
                    flags.add("auto_prob")
                s_prob = self._sales_prob_score(lead.probability or 0.0)
            if not ruler:
                flags.add("untagged")

            total = s_stage + s_velocity + s_value + s_timing + s_prob
            max_points = SALES_MAX_POINTS[stage_key]
            deals.append({
                "id": lead.id,
                "name": lead.name or "?",
                "user": lead.user_id.name or _("Unassigned"),
                "user_id": lead.user_id.id,
                "stage": stage_key,
                "ruler": ruler,
                "usd": usd_amount,
                "age": age,
                "deadline": deadline,
                "prob": lead.probability or 0.0,
                "late_stage": late_stage,
                "scores": (s_stage, s_velocity, s_value, s_timing, s_prob),
                "total": total,
                "max": max_points,
                "strength": total / max_points * 100.0,
                "flags": flags,
                "milestones": {field: bool(lead[field])
                               for field, _label in milestone_fields},
            })
        return {
            "deals": deals, "won": won, "lost": lost,
            "usd": usd, "today": today, "year": year,
            "milestone_fields": milestone_fields,
        }

    # ------------------------------------------------------------------
    # Widget dict builders
    # ------------------------------------------------------------------
    def _sales_kpi(self, wid, name, value, fmt, caption, color, help_text,
                   domain=None, modal_table=False, points=None, span=3):
        return {
            "id": wid, "name": name, "type": "kpi",
            "model": "crm.lead", "mode": "computed",
            "measure": caption, "groupby": "", "color": color,
            "help": help_text, "value": float(value), "format": fmt,
            "domain": self._json_safe(domain or []),
            "points": points or [], "rows": [], "columns": [],
            "span": span, "error": False,
            "modal_table": modal_table,
        }

    def _sales_matrix(self, wid, name, rows, columns, help_text, groupby,
                      span=6, compact=False, color="#2563eb"):
        # The shared MatrixTable template keys rows by label; two deals with
        # the same name would crash the OWL loop — suffix duplicates.
        seen = {}
        for row in rows:
            label = row.get("label") or "?"
            if label in seen:
                seen[label] += 1
                row["label"] = "%s (%s)" % (label, seen[label])
            else:
                seen[label] = 1
        widget = {
            "id": wid, "name": name, "type": "matrix",
            "model": "crm.lead", "mode": "computed",
            "measure": "", "groupby": groupby, "color": color,
            "help": help_text, "value": float(len(rows)),
            "format": "integer", "domain": [], "points": [],
            "rows": rows, "columns": columns, "span": span, "error": False,
        }
        if compact:
            widget["compact"] = True
        return widget

    def _sales_bar(self, wid, name, points, help_text, measure, groupby,
                   span=6, fmt="integer", color="#2563eb"):
        return {
            "id": wid, "name": name, "type": "bar",
            "model": "crm.lead", "mode": "computed",
            "measure": measure, "groupby": groupby, "color": color,
            "help": help_text, "value": float(len(points)), "format": fmt,
            "domain": [], "points": points, "rows": [], "columns": [],
            "span": span, "error": False,
        }

    def _sales_funnel(self, wid, name, points, help_text, span=6):
        return {
            "id": wid, "name": name, "type": "funnel",
            "model": "crm.lead", "mode": "computed",
            "measure": _("Deals"), "groupby": _("Milestone"),
            "color": "#2563eb", "help": help_text,
            "value": float(points[0]["value"]) if points else 0.0,
            "format": "integer", "domain": [], "points": points,
            "rows": [], "columns": [], "span": span, "error": False,
        }

    def _sales_pie(self, wid, name, points, help_text, total, span=4):
        return {
            "id": wid, "name": name, "type": "pie",
            "model": "crm.lead", "mode": "computed",
            "measure": _("Deals"), "groupby": _("Path"), "color": "#2563eb",
            "help": help_text, "value": float(total), "format": "integer",
            "domain": [], "points": points, "rows": [], "columns": [],
            "span": span, "error": False,
        }

    def _sales_ids_domain(self, ids):
        return self._json_safe([("id", "in", list(ids))])

    def _sales_score_text(self, deal):
        cells = []
        for index, score in enumerate(deal["scores"]):
            locked = index >= 3 and not deal["late_stage"]
            cells.append("–" if locked else str(score))
        return "·".join(cells)

    def _sales_close_text(self, deal):
        if not deal["late_stage"]:
            return self._ops_date_text(deal["deadline"]) if deal["deadline"] else "—"
        if "no_deadline" in deal["flags"]:
            return _("missing ⚠")
        if "overdue" in deal["flags"]:
            return _("%s ⚠") % self._ops_date_text(deal["deadline"])
        return self._ops_date_text(deal["deadline"])

    def _sales_deal_row(self, deal, usd, with_scores=True):
        row = {
            "label": deal["name"],
            "domain": self._json_safe([("id", "=", deal["id"])]),
            "rep": deal["user"],
            "stage": SALES_STAGE_LABELS[deal["stage"]],
            "path": (_("NetSuite") if deal["ruler"] == "netsuite"
                     else _("Odoo") if deal["ruler"] == "odoo" else _("— ⚠")),
            "value": self._ops_money(deal["usd"], usd),
            "age": _("%sd") % deal["age"],
            "close": self._sales_close_text(deal),
            "strength": self._ops_pct_text(deal["strength"]),
            "tones": {
                "strength": self._sales_strength_tone(deal["strength"]),
                "close": ("bad" if deal["flags"] & {"overdue", "no_deadline"}
                          else ""),
            },
        }
        if with_scores:
            row["score"] = self._sales_score_text(deal)
        return row

    def _sales_deal_columns(self, with_scores=True):
        columns = [
            {"key": "rep", "label": _("Rep"), "format": "text"},
            {"key": "stage", "label": _("Stage"), "format": "text"},
            {"key": "path", "label": _("Path"), "format": "text"},
            {"key": "value", "label": _("Value (USD)"), "format": "money"},
            {"key": "age", "label": _("Age"), "format": "money"},
            {"key": "close", "label": _("Exp. close"), "format": "text"},
        ]
        if with_scores:
            columns.append({"key": "score", "label": _("S·V·$·T·P"), "format": "text"})
        columns.append({"key": "strength", "label": _("Strength"), "format": "money"})
        return columns

    def _sales_deals_table(self, wid, name, deals, usd, help_text,
                           with_scores=True):
        rows = [self._sales_deal_row(deal, usd, with_scores=with_scores)
                for deal in sorted(deals, key=lambda d: -d["usd"])]
        total_usd = sum(deal["usd"] for deal in deals)
        avg = (sum(deal["strength"] for deal in deals) / len(deals)
               if deals else 0.0)
        total_row = {
            "label": _("Total (%s deals)") % len(deals),
            "domain": self._sales_ids_domain([d["id"] for d in deals]),
            "rep": "", "stage": "", "path": "",
            "value": self._ops_money(total_usd, usd),
            "age": "", "close": "",
            "strength": self._ops_pct_text(avg),
            "tones": {"strength": self._sales_strength_tone(avg)},
        }
        if with_scores:
            total_row["score"] = ""
        return self._sales_matrix(
            wid, name, rows + [total_row],
            self._sales_deal_columns(with_scores=with_scores),
            help_text, _("Deal"), span=12)

    def _sales_wins_table(self, wid, name, won, usd, help_text, by_cycle=False):
        entries = sorted(won, key=lambda w: (w["cycle"] or 0) if by_cycle
                         else -w["usd"], reverse=by_cycle)
        rows = []
        for win in entries:
            rows.append({
                "label": win["name"],
                "domain": self._json_safe([("id", "=", win["id"])]),
                "rep": win["user"],
                "value": self._ops_money(win["usd"], usd),
                "closed": self._ops_date_text(win["closed"]),
                "cycle": _("%sd") % win["cycle"] if win["cycle"] is not None else "—",
                "tones": {"value": "warn" if win["usd"] <= 0 else ""},
            })
        cycles = [w["cycle"] for w in won if w["cycle"] is not None]
        rows.append({
            "label": _("Total (%s wins)") % len(won),
            "domain": self._sales_ids_domain([w["id"] for w in won]),
            "rep": "",
            "value": self._ops_money(sum(w["usd"] for w in won), usd),
            "closed": "",
            "cycle": _("avg %sd") % round(sum(cycles) / len(cycles)) if cycles else "—",
            "tones": {},
        })
        return self._sales_matrix(
            wid, name, rows,
            [
                {"key": "rep", "label": _("Rep"), "format": "text"},
                {"key": "value", "label": _("Value (USD)"), "format": "money"},
                {"key": "closed", "label": _("Closed"), "format": "text"},
                {"key": "cycle", "label": _("Cycle"), "format": "money"},
            ],
            help_text, _("Deal"), span=12)

    def _sales_hygiene_table(self, wid, name, deals, usd, extra_key,
                             extra_label, extra_getter, help_text):
        rows = []
        for deal in sorted(deals, key=lambda d: -d["usd"]):
            rows.append({
                "label": deal["name"],
                "domain": self._json_safe([("id", "=", deal["id"])]),
                "rep": deal["user"],
                "stage": SALES_STAGE_LABELS[deal["stage"]],
                "value": self._ops_money(deal["usd"], usd),
                extra_key: extra_getter(deal),
                "tones": {},
            })
        return self._sales_matrix(
            wid, name, rows,
            [
                {"key": "rep", "label": _("Rep"), "format": "text"},
                {"key": "stage", "label": _("Stage"), "format": "text"},
                {"key": "value", "label": _("Value (USD)"), "format": "money"},
                {"key": extra_key, "label": extra_label, "format": "text"},
            ],
            help_text, _("Deal"), span=12)

    def _sales_hygiene_kpi(self, wid, name, deals, caption, help_text, usd,
                           extra_key, extra_label, extra_getter):
        count = len(deals)
        return self._sales_kpi(
            wid, name, count, "integer", caption,
            "#dc2626" if count else "#059669",
            help_text + _(" Click for the list."),
            domain=self._sales_ids_domain([d["id"] for d in deals]),
            modal_table=self._sales_hygiene_table(
                wid + "_list", name, deals, usd,
                extra_key, extra_label, extra_getter, help_text)
            if deals else False)

    # ------------------------------------------------------------------
    # The dashboard
    # ------------------------------------------------------------------
    def _sales_dashboard_widgets(self, date_from=False, date_to=False,
                                 filters=False):
        selected = self._sales_selected(filters)
        data = self._sales_collect(selected)
        deals, won, lost = data["deals"], data["won"], data["lost"]
        usd, today, year = data["usd"], data["today"], data["year"]
        usd_note = ("" if usd.name == "USD"
                    else _(" ⚠ USD not found — amounts shown in %s.") % usd.name)
        rate_note = _(" All money in USD at the newest stored rates.")

        count = len(deals)
        pipeline_usd = sum(deal["usd"] for deal in deals)
        weighted_usd = sum(deal["usd"] * deal["strength"] / 100.0
                           for deal in deals)
        avg_strength = (sum(deal["strength"] for deal in deals) / count
                        if count else 0.0)
        won_usd = sum(win["usd"] for win in won)
        closed_count = len(won) + len(lost)
        win_rate = len(won) / closed_count * 100.0 if closed_count else 0.0
        cycles = [win["cycle"] for win in won if win["cycle"] is not None]
        avg_cycle = sum(cycles) / len(cycles) if cycles else 0.0

        # Monthly won sparkline (elapsed months only for the running year).
        last_month = today.month if year == today.year else 12
        monthly = []
        for month in range(1, last_month + 1):
            monthly.append({
                "label": SALES_MONTH_LABELS[month - 1],
                "value": round(sum(w["usd"] for w in won
                                   if w["month"] == month)),
                "color": "#059669", "domain": [], "detail": None,
            })

        methodology = _(
            "Strength = points earned ÷ stage maximum (Attract 7 · Engage 9 "
            "· Advise 11 · Align 23 · Persuade 25). Axes: Stage, Velocity "
            "(age vs the stage's clock), Value (NetSuite/Odoo ARR ruler), "
            "Timing and Probability (Align/Persuade only, after the JEP).")
        # Fallback click target when a year has no wins yet: the (empty)
        # wins list, never the raw all-leads table.
        won_domain = self._sales_ids_domain([w["id"] for w in won])

        widgets = [
            self._sales_kpi(
                "sales_pipeline", _("Active Pipeline (USD)"), pipeline_usd,
                "usd",
                _("%(n)s deals · %(weighted)s strength-weighted") % {
                    "n": count,
                    "weighted": self._ops_money(weighted_usd, usd)},
                "#2563eb",
                _("Every open opportunity on the five SCA stages, all "
                  "sources and teams (use the filters to slice). "
                  "Strength-weighted = each deal's value × its strength — "
                  "pipeline you can believe. Click for every deal.")
                + rate_note + usd_note,
                modal_table=self._sales_deals_table(
                    "sales_pipeline_deals", _("Active Pipeline — All Deals"),
                    deals, usd,
                    _("Sorted by value.") + rate_note + usd_note)),
            self._sales_kpi(
                "sales_strength", _("Pipeline Strength"), avg_strength,
                "percent",
                _("average of %(n)s deals · max 25 points each") % {"n": count},
                ("#059669" if avg_strength >= STRENGTH_GOOD_FROM
                 else "#b45309" if avg_strength >= STRENGTH_WARN_FROM
                 else "#dc2626"),
                methodology + _(" Click for the per-stage summary."),
                modal_table=self._sales_strength_table(deals, usd)),
            self._sales_kpi(
                "sales_won", _("Won %s · Win Rate") % year, won_usd, "usd",
                _("%(wins)s wins of %(closed)s closed · %(rate)s win rate") % {
                    "wins": len(won), "closed": closed_count,
                    "rate": self._ops_pct_text(win_rate)},
                "#059669",
                _("Deals marked Won with a %(year)s close date; win rate = "
                  "won ÷ (won + lost) closed in %(year)s. The sparkline is "
                  "won value by month. Click for the wins list.")
                % {"year": year} + rate_note + usd_note,
                domain=won_domain,
                points=monthly,
                modal_table=self._sales_wins_table(
                    "sales_won_list", _("%s Wins") % year, won, usd,
                    _("Won deals, biggest first.") + rate_note + usd_note)
                if won else False),
            self._sales_kpi(
                "sales_cycle", _("Avg Sales Cycle"), avg_cycle, "days",
                _("create → won, across %s wins") % len(cycles),
                "#7c3aed",
                _("Average days from opportunity creation to the won date, "
                  "over %s wins. Click for the per-win cycle.") % year,
                domain=won_domain,
                modal_table=self._sales_wins_table(
                    "sales_cycle_list", _("%s Wins by Cycle") % year, won,
                    usd, _("Longest sales cycles first."), by_cycle=True)
                if won else False),
        ]

        widgets.append(self._sales_stage_ladder(deals, usd))
        widgets.append(self._sales_axis_bar(deals))
        widgets.append(self._sales_board(deals, usd, rate_note + usd_note))
        widgets.append(self._sales_path_pie(deals, usd))
        widgets.append(self._sales_leaderboard(deals, usd))
        widgets.append(self._sales_cold_money(deals, usd, pipeline_usd))
        funnel = self._sales_milestone_funnel(deals, data["milestone_fields"])
        if funnel:
            widgets.append(funnel)
        widgets.append(self._sales_lost_bar(lost, usd, year))
        widgets += self._sales_hygiene_row(deals, usd)
        return widgets

    # ------------------------------------------------------------------
    # Row 2 — ladder + axis diagnosis
    # ------------------------------------------------------------------
    def _sales_stage_groups(self, deals):
        groups = []
        for key in SALES_STAGE_ORDER:
            grp = [d for d in deals if d["stage"] == key]
            groups.append((key, grp))
        return groups

    def _sales_strength_table(self, deals, usd):
        rows = []
        for key, grp in self._sales_stage_groups(deals):
            avg = (sum(d["strength"] for d in grp) / len(grp)) if grp else 0.0
            rows.append({
                "label": SALES_STAGE_LABELS[key],
                "domain": self._sales_ids_domain([d["id"] for d in grp]),
                "n": "%d" % len(grp),
                "value": self._ops_money(sum(d["usd"] for d in grp), usd),
                "strength": self._ops_pct_text(avg) if grp else "—",
                "tones": {"strength": self._sales_strength_tone(avg) if grp else ""},
            })
        count = len(deals)
        avg_all = (sum(d["strength"] for d in deals) / count) if count else 0.0
        rows.append({
            "label": _("All stages"),
            "domain": self._sales_ids_domain([d["id"] for d in deals]),
            "n": "%d" % count,
            "value": self._ops_money(sum(d["usd"] for d in deals), usd),
            "strength": self._ops_pct_text(avg_all) if count else "—",
            "tones": {"strength": self._sales_strength_tone(avg_all) if count else ""},
        })
        return self._sales_matrix(
            "sales_strength_stages", _("Strength by Stage"), rows,
            [
                {"key": "n", "label": _("Deals"), "format": "text"},
                {"key": "value", "label": _("Value (USD)"), "format": "money"},
                {"key": "strength", "label": _("Avg strength"), "format": "money"},
            ],
            _("Average deal strength per SCA stage."), _("Stage"), span=12)

    def _sales_stage_ladder(self, deals, usd):
        ladder = self._sales_strength_table(deals, usd)
        ladder["id"] = "sales_stage_ladder"
        ladder["name"] = _("Strength Ladder — by Stage")
        ladder["span"] = 6
        ladder["compact"] = True
        ladder["help"] = _(
            "Deal count, value and average strength per stage; click a row "
            "for that stage's deals.")
        return ladder

    def _sales_axis_bar(self, deals):
        count = len(deals) or 1
        axes = [
            (_("Stage"), 0), (_("Velocity"), 1), (_("Value"), 2),
            (_("Timing"), 3), (_("Probability"), 4),
        ]
        points = []
        all_ids = [d["id"] for d in deals]
        for label, index in axes:
            avg = sum(d["scores"][index] for d in deals) / count
            points.append({
                "label": label,
                "value": round(avg, 2),
                "color": ("#2563eb" if avg >= 2.5
                          else "#f59e0b" if avg >= 1.25 else "#dc2626"),
                "domain": self._sales_ids_domain(all_ids),
            })
        points.sort(key=lambda p: -p["value"])
        return self._sales_bar(
            "sales_axis_diagnosis", _("Axis Diagnosis — where strength leaks"),
            points,
            _("Average points per scoring axis across the active pipeline "
              "(each axis is worth up to 5). Red axes are where the "
              "pipeline bleeds — Timing and Probability only score on "
              "Align/Persuade deals after a JEP."),
            _("Avg points (of 5)"), _("Axis"), span=6, fmt="number")

    # ------------------------------------------------------------------
    # Row 3 — deal board + path pie
    # ------------------------------------------------------------------
    def _sales_board(self, deals, usd, note):
        top = sorted(deals, key=lambda d: -d["usd"])[:20]
        board = self._sales_deals_table(
            "sales_deal_board", _("Deal Strength Board"), top, usd,
            _("Top %(top)s of %(n)s deals by value — open the Active "
              "Pipeline card for every deal. S·V·$·T·P = points per axis; "
              "“–” = axis locked before the JEP (Align/Persuade).")
            % {"top": len(top), "n": len(deals)} + note)
        board["span"] = 8
        # The total row of the top-20 slice would read as a pipeline total;
        # drop it (the Active Pipeline card owns the true total).
        board["rows"] = board["rows"][:-1]
        return board

    def _sales_path_pie(self, deals, usd):
        segments = [
            ("netsuite", _("NetSuite")),
            ("odoo", _("Odoo")),
            (None, _("Untagged ⚠")),
        ]
        points = []
        for ruler, label in segments:
            grp = [d for d in deals if d["ruler"] == ruler]
            if not grp:
                continue
            points.append({
                "label": _("%(label)s · %(usd)s") % {
                    "label": label,
                    "usd": self._ops_money(sum(d["usd"] for d in grp), usd)},
                "value": len(grp),
                "domain": self._sales_ids_domain([d["id"] for d in grp]),
            })
        return self._sales_pie(
            "sales_path_pie", _("NetSuite vs Odoo"), points,
            _("Active deals by path tag — the tag picks which value ruler "
              "scores the deal (NetSuite $10k-40k bands, Odoo $2.5k-10k). "
              "Untagged deals score on the NetSuite ruler and are flagged "
              "in hygiene."),
            len(deals))

    # ------------------------------------------------------------------
    # Row 4 — leaderboard + cold money
    # ------------------------------------------------------------------
    def _sales_leaderboard(self, deals, usd):
        by_user = {}
        for deal in deals:
            by_user.setdefault(deal["user"], []).append(deal)
        entries = []
        # NB: do not name a local "user" in any function that calls _() —
        # Odoo 19's translation helper reads the caller's locals and does
        # int(user) on it (crashed with a salesperson NAME here once).
        for rep_name, grp in by_user.items():
            weighted = sum(d["usd"] * d["strength"] / 100.0 for d in grp)
            entries.append({
                "user": rep_name, "grp": grp, "weighted": weighted,
                "usd": sum(d["usd"] for d in grp),
                "avg": sum(d["strength"] for d in grp) / len(grp),
            })
        entries.sort(key=lambda e: -e["weighted"])
        rows = []
        for entry in entries:
            rows.append({
                "label": entry["user"],
                "domain": self._sales_ids_domain(
                    [d["id"] for d in entry["grp"]]),
                "n": "%d" % len(entry["grp"]),
                "usd": self._ops_money(entry["usd"], usd),
                "weighted": self._ops_money(entry["weighted"], usd),
                "avg": self._ops_pct_text(entry["avg"]),
                "tones": {"avg": self._sales_strength_tone(entry["avg"])},
            })
        return self._sales_matrix(
            "sales_leaderboard", _("Salesperson Leaderboard"), rows,
            [
                {"key": "n", "label": _("Deals"), "format": "text"},
                {"key": "usd", "label": _("Pipeline (USD)"), "format": "money"},
                {"key": "weighted", "label": _("Strength-weighted"), "format": "money"},
                {"key": "avg", "label": _("Avg strength"), "format": "money"},
            ],
            _("Ranked by strength-weighted pipeline (deal value × strength) "
              "— the pipeline you can believe. Click a row for that rep's "
              "deals."),
            _("Salesperson"), span=6, compact=True)

    def _sales_cold_money(self, deals, usd, pipeline_usd):
        stalled = sorted([d for d in deals if d["scores"][1] == 0],
                         key=lambda d: -d["usd"])
        top = stalled[:8]
        stalled_usd = sum(d["usd"] for d in stalled)
        share = stalled_usd / pipeline_usd * 100.0 if pipeline_usd else 0.0
        rows = []
        for deal in top:
            rows.append({
                "label": deal["name"],
                "domain": self._json_safe([("id", "=", deal["id"])]),
                "rep": deal["user"],
                "stage": SALES_STAGE_LABELS[deal["stage"]],
                "value": self._ops_money(deal["usd"], usd),
                "age": _("%sd") % deal["age"],
                "tones": {"age": "bad"},
            })
        rows.append({
            "label": _("All stalled (%s deals)") % len(stalled),
            "domain": self._sales_ids_domain([d["id"] for d in stalled]),
            "rep": "", "stage": "",
            "value": self._ops_money(stalled_usd, usd),
            "age": self._ops_pct_text(share) + _(" of pipeline"),
            "tones": {"age": "bad" if share >= 50 else "warn"},
        })
        return self._sales_matrix(
            "sales_cold_money", _("Money Going Cold — velocity 0"), rows,
            [
                {"key": "rep", "label": _("Rep"), "format": "text"},
                {"key": "stage", "label": _("Stage"), "format": "text"},
                {"key": "value", "label": _("Value (USD)"), "format": "money"},
                {"key": "age", "label": _("Age"), "format": "money"},
            ],
            _("Deals that have outstayed their stage's clock (velocity "
              "score 0), biggest first — top 8 shown, the total row covers "
              "all of them. Click a row to open the deal."),
            _("Deal"), span=6, compact=True)

    # ------------------------------------------------------------------
    # Row 5 — milestones + lost reasons
    # ------------------------------------------------------------------
    def _sales_milestone_funnel(self, deals, milestone_fields):
        if not milestone_fields:
            return False
        points = []
        for field, label in milestone_fields:
            grp = [d for d in deals if d["milestones"].get(field)]
            points.append({
                "label": _(label),
                "value": len(grp),
                "domain": self._sales_ids_domain([d["id"] for d in grp]),
            })
        return self._sales_funnel(
            "sales_milestones", _("SCA Milestone Funnel"), points,
            _("How many active deals carry each SCA milestone date "
              "(Studio fields on the lead). A later milestone larger than "
              "an earlier one means dates are being skipped in Odoo."))

    def _sales_lost_bar(self, lost, usd, year):
        by_reason = {}
        for entry in lost:
            rec = by_reason.setdefault(
                entry["reason"], {"n": 0, "usd": 0.0, "ids": []})
            rec["n"] += 1
            rec["usd"] += entry["usd"]
            rec["ids"].append(entry["id"])
        ranked = sorted(by_reason.items(), key=lambda kv: -kv[1]["n"])[:8]
        points = []
        for reason, rec in ranked:
            points.append({
                "label": _("%(reason)s · %(usd)s") % {
                    "reason": reason,
                    "usd": self._ops_money(rec["usd"], usd)},
                "value": rec["n"],
                "color": ("#dc2626" if reason == _("(no reason)")
                          else "#94a3b8"),
                "domain": self._sales_ids_domain(rec["ids"]),
            })
        return self._sales_bar(
            "sales_lost_reasons", _("Why We Lose — %s") % year, points,
            _("Lost deals of %(year)s by reason (count; the label carries "
              "the USD value lost). Red = deals lost with NO reason set — "
              "fix those in CRM. Click a bar for the deals behind it.")
            % {"year": year},
            _("Lost deals"), _("Reason"), span=6, color="#64748b")

    # ------------------------------------------------------------------
    # Row 6 — hygiene
    # ------------------------------------------------------------------
    def _sales_hygiene_row(self, deals, usd):
        late = [d for d in deals if d["late_stage"]]
        auto = [d for d in late if "auto_prob" in d["flags"]]
        overdue = [d for d in deals if "overdue" in d["flags"]]
        nodate = [d for d in deals if "no_deadline" in d["flags"]]
        untagged = [d for d in deals if "untagged" in d["flags"]]
        return [
            self._sales_hygiene_kpi(
                "sales_hyg_prob", _("JEP % Not Set"), auto,
                _("of %s Align/Persuade deals") % len(late),
                _("Align/Persuade deals still carrying Odoo's automated "
                  "probability — the Sales Manager has not entered a "
                  "discretionary JEP win %. They score whatever the field "
                  "holds, but the number is not a decision."),
                usd, "prob", _("Probability"),
                lambda d: _("%s%% (auto)") % round(d["prob"], 1)),
            self._sales_hygiene_kpi(
                "sales_hyg_overdue", _("Overdue Close Dates"), overdue,
                _("expected close in the past"),
                _("Align/Persuade deals whose expected close date has "
                  "passed — either the deal slipped or the date is stale. "
                  "They earn 0 Timing points until fixed."),
                usd, "close", _("Exp. close"),
                lambda d: self._ops_date_text(d["deadline"])),
            self._sales_hygiene_kpi(
                "sales_hyg_nodate", _("No Close Date"), nodate,
                _("Align/Persuade without a date"),
                _("Align/Persuade deals with no expected close date — the "
                  "JEP should set one (decision date rounded to month-end). "
                  "They earn 0 Timing points until it exists."),
                usd, "close", _("Exp. close"), lambda d: _("missing")),
            self._sales_hygiene_kpi(
                "sales_hyg_untagged", _("Untagged Deals"), untagged,
                _("no NetSuite/Odoo tag"),
                _("Deals with neither a NetSuite nor an Odoo tag — the tag "
                  "picks the value ruler. Untagged deals score on the "
                  "NetSuite ruler by default."),
                usd, "path", _("Path"), lambda d: _("untagged")),
        ]
