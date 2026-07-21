import json
from datetime import date

from odoo import fields, models, _

TIER_DASHBOARD_NAME = "Odoo Partnership Tier"
TIER_COLOR = "#7d4b78"

# Odoo partner-tier thresholds (Ferry Nauli call 2026-07-13).
SILVER_USERS, GOLD_USERS = 75, 300
SILVER_CONSULTANTS, GOLD_CONSULTANTS = 3, 6
SILVER_RETENTION, GOLD_RETENTION = 70.0, 80.0

# CRM Studio fields: actual licenses on won deals / forecast on open deals.
TIER_USERS_FIELD = "x_studio_no_of_users"
TIER_EXPECTED_FIELD = "x_studio_expected_user_license"

# Chart display starts here (Akshay: "tracking from Jan 26"); older cohorts
# still count inside any trailing window they overlap so numbers reconcile.
TIER_DISPLAY_START = date(2026, 1, 1)
TIER_FORECAST_MONTHS = 12

# Review calendar = SA financial year (Akshay overrides Ferry's Indonesia
# calendar): FY starts 1 Feb; quarter starts Feb / May / Aug / Nov.
SA_QUARTER_MONTHS = (2, 5, 8, 11)

# Editable without code: Settings → Technical → System Parameters.
PARAM_CONSULTANTS = "linkederp_dashboard.tier_consultants"
PARAM_ARR_TARGET = "linkederp_dashboard.tier_arr_target_usd"
PARAM_Q_TARGET = "linkederp_dashboard.tier_license_quarter_target"
PARAM_INTERNAL = "linkederp_dashboard.tier_internal_cohorts"
DEFAULT_CONSULTANTS = "Ferry Nauli,Deepa Kalmath,Prathuk Hegde"
DEFAULT_ARR_TARGET = 200000.0
DEFAULT_Q_TARGET = 50

# Company grouping by res.company name token.
TIER_COMPANY_TOKENS = (("mrelate", "Mrelate · India"),
                       ("istana", "PT Istana · Indonesia"),
                       ("linked", "LinkedERP · South Africa"))
TIER_OTHER_COMPANY = "Other"


def _month_start(day):
    return date(day.year, day.month, 1)


def _month_add(day, months):
    month_index = day.year * 12 + (day.month - 1) + months
    return date(month_index // 12, month_index % 12 + 1, 1)


class LinkederpDashboardTier(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_tier_dashboard()

    def _ensure_tier_dashboard(self):
        if self._ensure_dashboard_name(TIER_DASHBOARD_NAME, []):
            return
        if "crm.lead" not in self.env:
            return
        self.create({
            "name": TIER_DASHBOARD_NAME,
            "sequence": 85,
            "bucket": "management",
            "description": _(
                "Odoo partnership tier (Silver/Gold) health and forecast: "
                "trailing-12-month user licenses, certified consultants, "
                "retention, pipeline projection and sales targets."
            ),
            "color": TIER_COLOR,
        })

    def _is_tier_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == TIER_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Config (System Parameters, code defaults)
    # ------------------------------------------------------------------
    def _tier_param(self, key, default):
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        return value if value not in (False, None, "") else default

    def _tier_consultants(self):
        names = [n.strip() for n in
                 str(self._tier_param(PARAM_CONSULTANTS, DEFAULT_CONSULTANTS)).split(",")]
        return [n for n in names if n]

    def _tier_arr_target(self):
        try:
            return float(self._tier_param(PARAM_ARR_TARGET, DEFAULT_ARR_TARGET))
        except (TypeError, ValueError):
            return DEFAULT_ARR_TARGET

    def _tier_q_target(self):
        try:
            return int(float(self._tier_param(PARAM_Q_TARGET, DEFAULT_Q_TARGET)))
        except (TypeError, ValueError):
            return DEFAULT_Q_TARGET

    def _tier_internal_cohorts(self):
        """[{month: date, users: int, label}] from the JSON system parameter —
        LinkedERP's own internal licenses (Akshay: include, no spreadsheet)."""
        raw = self._tier_param(PARAM_INTERNAL, "[]")
        cohorts = []
        try:
            for row in json.loads(raw):
                month = fields.Date.to_date("%s-01" % row.get("month"))
                users = int(row.get("users") or 0)
                if month and users:
                    cohorts.append({
                        "month": _month_start(month), "users": users,
                        "label": row.get("label") or _("LinkedERP internal"),
                        "company": "LinkedERP · South Africa",
                        "lead_id": False,
                    })
        except (ValueError, TypeError, AttributeError):
            pass  # malformed config: dashboard still renders, hygiene flags it
        return cohorts

    # ------------------------------------------------------------------
    # Cohorts
    # ------------------------------------------------------------------
    def _tier_company_label(self, company_name):
        low = (company_name or "").lower()
        for token, label in TIER_COMPANY_TOKENS:
            if token in low:
                return label
        return TIER_OTHER_COMPANY

    def _tier_lead_model(self):
        return self.env["crm.lead"].with_context(active_test=False)

    def _tier_won_cohorts(self):
        """One cohort per won deal carrying user licenses; the users field
        itself is the 'this is an Odoo licence deal' filter."""
        if TIER_USERS_FIELD not in self._tier_lead_model()._fields:
            return []
        leads = self._tier_lead_model().search_read(
            [("stage_id.is_won", "=", True), (TIER_USERS_FIELD, ">", 0)],
            ["name", "partner_id", TIER_USERS_FIELD, "date_closed",
             "company_id", "expected_revenue"])
        cohorts = []
        for lead in leads:
            closed = fields.Datetime.to_datetime(lead.get("date_closed"))
            if not closed:
                continue
            cohorts.append({
                "month": _month_start(closed.date()),
                "users": int(lead[TIER_USERS_FIELD]),
                "label": (lead["partner_id"][1] if lead.get("partner_id")
                          else lead["name"]),
                "company": self._tier_company_label(
                    lead["company_id"][1] if lead.get("company_id") else ""),
                "company_id": lead["company_id"][0] if lead.get("company_id") else False,
                "revenue": lead.get("expected_revenue") or 0.0,
                "lead_id": lead["id"],
            })
        return cohorts

    def _tier_pipeline_cohorts(self):
        """Open opps with an expected licence count: contribute from the month
        AFTER expected close, for 12 months (Akshay's forecast rule)."""
        if TIER_EXPECTED_FIELD not in self._tier_lead_model()._fields:
            return []
        leads = self._tier_lead_model().search_read(
            [("type", "=", "opportunity"), ("active", "=", True),
             ("stage_id.is_won", "=", False), (TIER_EXPECTED_FIELD, ">", 0)],
            ["name", "partner_id", TIER_EXPECTED_FIELD, "date_deadline",
             "company_id"])
        cohorts, undated = [], []
        for lead in leads:
            deadline = fields.Date.to_date(lead.get("date_deadline"))
            entry = {
                "users": int(lead[TIER_EXPECTED_FIELD]),
                "label": (lead["partner_id"][1] if lead.get("partner_id")
                          else lead["name"]),
                "company": self._tier_company_label(
                    lead["company_id"][1] if lead.get("company_id") else ""),
                "lead_id": lead["id"],
                "deadline": deadline,
            }
            if deadline:
                entry["month"] = _month_add(_month_start(deadline), 1)
                cohorts.append(entry)
            else:
                undated.append(entry)
        return cohorts + [dict(e, month=None) for e in undated]

    @staticmethod
    def _tier_trailing(cohorts, month):
        """Users active in the trailing-12m window ending at `month`:
        a cohort counts for 12 months starting its own month."""
        total = 0
        for cohort in cohorts:
            if not cohort.get("month"):
                continue
            age = (month.year * 12 + month.month) - \
                (cohort["month"].year * 12 + cohort["month"].month)
            if 0 <= age < 12:
                total += cohort["users"]
        return total

    # ------------------------------------------------------------------
    # SA financial year helpers
    # ------------------------------------------------------------------
    def _tier_sa_quarter_start(self, day):
        candidates = []
        for year in (day.year - 1, day.year):
            candidates += [date(year, m, 1) for m in SA_QUARTER_MONTHS]
        return max(c for c in candidates if c <= day)

    def _tier_next_reviews(self, day, count=4):
        candidates = []
        for year in (day.year, day.year + 1, day.year + 2):
            candidates += [date(year, m, 1) for m in SA_QUARTER_MONTHS]
        return sorted(c for c in candidates if c > day)[:count]

    def _tier_sa_fy_start(self, day):
        return date(day.year if day.month >= 2 else day.year - 1, 2, 1)

    # ------------------------------------------------------------------
    # Shared modal builder (MatrixTable shape)
    # ------------------------------------------------------------------
    def _tier_modal(self, name, help_text, groupby, columns, rows):
        return {"name": name, "help": help_text, "color": TIER_COLOR,
                "groupby": groupby, "compact": True,
                "columns": columns, "rows": rows}

    def _tier_kpi(self, wid, name, value, measure, info, span=3,
                  value_text=False, modal=False, model="", domain=None,
                  value_format="integer", scale=False, color=TIER_COLOR,
                  chips=False, coin=False):
        return {
            "id": wid, "name": name, "type": "kpi", "model": model,
            "mode": "computed", "measure": measure, "groupby": "",
            "color": color, "help": "", "info": info,
            "value": float(value or 0), "format": value_format,
            "domain": self._json_safe(domain or []),
            "points": [], "rows": [], "columns": [], "span": span,
            "error": False, "modal_table": modal,
            "value_text": value_text, "scale": scale,
            # Mockup-v3 extras (guarded in the template; other dashboards
            # simply never set them): pass/fail pills + the tier metal coin.
            "chips": chips or [], "coin": coin,
        }

    def _tier_month_label(self, month):
        return month.strftime("%b '%y")

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------
    def _tier_dashboard_widgets(self, date_from=False, date_to=False, filters=False):
        today = fields.Date.context_today(self)
        this_month = _month_start(today)
        won = self._tier_won_cohorts()
        internal = self._tier_internal_cohorts()
        actual_cohorts = won + internal
        pipeline = [c for c in self._tier_pipeline_cohorts()]
        pipeline_dated = [c for c in pipeline if c.get("month")]
        pipeline_undated = [c for c in pipeline if not c.get("month")]

        trailing_now = self._tier_trailing(actual_cohorts, this_month)
        consultants = self._tier_consultants()
        arr_target = self._tier_arr_target()
        q_target = self._tier_q_target()

        # ---- retention (new sale.order field; may hold no data yet) ----
        retention_rate, renewed, churned, pending = None, 0, 0, 0
        Order = self.env["sale.order"]
        has_renewal_field = "odoo_renewal_outcome" in Order._fields
        if has_renewal_field:
            grouped = Order.read_group(
                [("odoo_renewal_outcome", "!=", False)],
                ["__count"], ["odoo_renewal_outcome"], lazy=False)
            counts = {row["odoo_renewal_outcome"]: row["__count"] for row in grouped}
            renewed = counts.get("renewed", 0)
            churned = counts.get("churned", 0)
            pending = counts.get("pending", 0)
            if renewed + churned:
                retention_rate = round(renewed / (renewed + churned) * 100, 1)

        # ---- trend months: display start → now → +12 ----
        # NEVER name a local `cursor` (or user/cr/env/uid) in a function that
        # calls _(): Odoo 19's translate frame-inspection grabs it as the DB
        # cursor and asserts (learning #12 family — this one bit us live).
        months = []
        month_cursor = TIER_DISPLAY_START
        horizon = _month_add(this_month, TIER_FORECAST_MONTHS)
        while month_cursor <= horizon:
            months.append(month_cursor)
            month_cursor = _month_add(month_cursor, 1)

        label_joins = _("joins")
        label_rolls = _("rolls off")

        trend_points = []
        silver_loss_month = None
        for month in months:
            committed = self._tier_trailing(actual_cohorts, month)
            with_pipe = committed + (
                self._tier_trailing(pipeline_dated, month) if month > this_month else 0)
            if month > this_month and committed < SILVER_USERS and not silver_loss_month:
                silver_loss_month = month
            joined = [c for c in actual_cohorts if c.get("month") == month]
            expiring = [c for c in actual_cohorts
                        if c.get("month") and _month_add(c["month"], 12) == month]
            modal_rows = [{
                "label": c["label"], "kind": label_joins, "users": c["users"],
                "model": "crm.lead" if c.get("lead_id") else "",
                "domain": self._json_safe([("id", "=", c["lead_id"])]) if c.get("lead_id") else [],
            } for c in joined] + [{
                "label": c["label"], "kind": label_rolls, "users": -c["users"],
                "model": "crm.lead" if c.get("lead_id") else "",
                "domain": self._json_safe([("id", "=", c["lead_id"])]) if c.get("lead_id") else [],
            } for c in expiring]
            # tierline series (mockup): actual solid to now, committed faded
            # from now, forecast dashed from now; None = not drawn.
            point = {
                "label": self._tier_month_label(month),
                "actual": committed if month <= this_month else None,
                "committed": committed if month >= this_month else None,
                "forecast": with_pipe if month >= this_month else None,
                "now": month == this_month,
            }
            if modal_rows:
                point["modal_table"] = self._tier_modal(
                    _("%s — cohort movement") % self._tier_month_label(month),
                    _("Deals starting or finishing their 12-month counting "
                      "window this month."),
                    _("Customer"),
                    [{"key": "kind", "label": _("Event"), "format": "text"},
                     {"key": "users", "label": _("Users"), "format": "integer"}],
                    modal_rows)
            trend_points.append(point)

        # ---- criteria verdicts ----
        users_silver = trailing_now >= SILVER_USERS
        users_gold = trailing_now >= GOLD_USERS
        cons_silver = len(consultants) >= SILVER_CONSULTANTS
        cons_gold = len(consultants) >= GOLD_CONSULTANTS
        ret_silver = retention_rate is None or retention_rate >= SILVER_RETENTION
        ret_gold = retention_rate is not None and retention_rate >= GOLD_RETENTION
        silver_ok = users_silver and cons_silver and ret_silver
        gold_ok = users_gold and cons_gold and ret_gold
        standing = _("Gold") if gold_ok else (_("Silver") if silver_ok else _("At risk"))

        # ---- company splits ----
        by_company = {}
        for cohort in actual_cohorts:
            if not cohort.get("month"):
                continue
            age = (this_month.year * 12 + this_month.month) - \
                (cohort["month"].year * 12 + cohort["month"].month)
            if 0 <= age < 12:
                by_company.setdefault(cohort["company"], []).append(cohort)

        # ---- ARR this SA FY (USD via the Finance factors) ----
        fy_start = self._tier_sa_fy_start(today)
        usd = self.env.ref("base.USD")
        companies = self.env["res.company"].sudo().search([])
        factors = self._fin_usd_factors(usd, today, companies)
        arr_by_company = {}
        for cohort in won:
            if cohort["month"] >= _month_start(fy_start):
                usd_value = (cohort.get("revenue") or 0.0) * factors.get(
                    cohort.get("company_id"), 1.0)
                arr_by_company[cohort["company"]] = \
                    arr_by_company.get(cohort["company"], 0.0) + usd_value
        arr_group = sum(arr_by_company.values())
        company_labels = [label for _t, label in TIER_COMPANY_TOKENS]
        group_target = arr_target * len(company_labels)

        # ---- current SA quarter users ----
        q_start = self._tier_sa_quarter_start(today)
        q_users_cohorts = [c for c in won if c["month"] >= _month_start(q_start)]
        q_users = sum(c["users"] for c in q_users_cohorts)

        # ---- widgets (mockup v3 layout, purpose-built widget types) ----
        usd_short = self._fin_usd_short
        widgets = []
        # Hoisted translations (learning #12: no _() inside comprehensions).
        missing_text = _("— missing")
        dash_text_placeholder = _("—")
        gold_user_gap = GOLD_USERS - trailing_now
        gold_cons_gap = GOLD_CONSULTANTS - len(consultants)
        silver_pos = round(SILVER_USERS / GOLD_USERS * 100)

        # Row 1 -- criteria scorecard (mockup cards: chips + banded scale).
        users_modal_rows = [{
            "label": c["label"], "company": c["company"], "users": c["users"],
            "since": self._tier_month_label(c["month"]),
            "until": self._tier_month_label(_month_add(c["month"], 12)),
            "model": "crm.lead" if c.get("lead_id") else "",
            "domain": self._json_safe([("id", "=", c["lead_id"])]) if c.get("lead_id") else [],
        } for c in sorted(
            (c for c in actual_cohorts if c.get("month")
             and 0 <= (this_month.year * 12 + this_month.month)
             - (c["month"].year * 12 + c["month"].month) < 12),
            key=lambda c: -c["users"])]
        widgets.append(self._tier_kpi(
            "tier_users", _("① New Users · trailing 12m"), trailing_now,
            "",
            _("Definition: user licences from won Odoo deals (plus LinkedERP's "
              "own internal licences), each counting for 12 months from its "
              "close month, then rolling off — Ferry's method, now live from "
              "Odoo. Calculation: sum of active cohorts in the window ending "
              "this month. Click for the cohort list."),
            modal=self._tier_modal(
                _("Active cohorts — trailing 12 months"),
                _("Each deal counts for 12 months from close."), _("Customer"),
                [{"key": "company", "label": _("Company"), "format": "text"},
                 {"key": "users", "label": _("Users"), "format": "integer"},
                 {"key": "since", "label": _("Counts from"), "format": "text"},
                 {"key": "until", "label": _("Rolls off"), "format": "text"}],
                users_modal_rows),
            scale={"pos": round(min(trailing_now / GOLD_USERS, 1.0) * 100, 1),
                   "label": "",
                   "style": ("background: linear-gradient(90deg, #8f9bab 0%, "
                             "#8f9bab {s}%, #d8b45c {s}%, #cf9f3b 100%);"
                             ).format(s=silver_pos),
                   "marks": [{"pos": silver_pos, "label": _("Silver %s") % SILVER_USERS},
                             {"pos": 100, "label": _("Gold %s") % GOLD_USERS,
                              "right": True}]},
            chips=[
                {"text": _("Silver ✓") if users_silver else _("Silver ✗"),
                 "tone": "ok" if users_silver else "no"},
                {"text": _("Gold ✓") if users_gold
                 else _("Gold — %s short") % gold_user_gap,
                 "tone": "ok" if users_gold else "no"},
            ],
        ))

        certified_label = _("Certified")
        widgets.append(self._tier_kpi(
            "tier_consultants", _("② Certified Consultants"), len(consultants),
            " · ".join(n.split()[0] for n in consultants),
            _("Definition: Odoo-certified consultants under LinkedERP's "
              "partner account. Calculation: the maintained list (Settings → "
              "Technical → System Parameters → %s). Click for the names.")
            % PARAM_CONSULTANTS,
            value_text=_("%(have)s / %(need)s")
            % {"have": len(consultants), "need": GOLD_CONSULTANTS},
            modal=self._tier_modal(
                _("Certified consultants"), _("Maintained list."), _("Consultant"),
                [{"key": "status", "label": _("Status"), "format": "text"}],
                [{"label": name, "status": certified_label}
                 for name in consultants]),
            chips=[
                {"text": _("Silver ✓ (need %s)") % SILVER_CONSULTANTS if cons_silver
                 else _("Silver ✗ (need %s)") % SILVER_CONSULTANTS,
                 "tone": "ok" if cons_silver else "no"},
                {"text": _("Gold ✓") if cons_gold
                 else _("Gold — %s short") % gold_cons_gap,
                 "tone": "ok" if cons_gold else "no"},
            ],
        ))

        retention_text = ("%s%%" % retention_rate) if retention_rate is not None \
            else _("— not tracked yet")
        retention_rows = []
        if has_renewal_field:
            for outcome, count in (("renewed", renewed), ("churned", churned),
                                   ("pending", pending)):
                retention_rows.append({
                    "label": outcome.capitalize(), "orders": count,
                    "model": "sale.order",
                    "domain": self._json_safe([("odoo_renewal_outcome", "=", outcome)]),
                })
        ret_tone = "wa" if retention_rate is None else \
            ("ok" if ret_silver else "no")
        widgets.append(self._tier_kpi(
            "tier_retention", _("③ Customer Retention"), retention_rate or 0,
            _("mark Renewal Outcome on renewal Sale Orders"),
            _("Definition: of the customers whose Odoo contract came up for "
              "renewal, the share that renewed. Calculation: Renewed ÷ "
              "(Renewed + Churned) using the 'Odoo Renewal Outcome' field on "
              "renewal Sale Orders; Pending is excluded. Click for the "
              "renewal orders."),
            value_text=retention_text,
            value_format="percent",
            modal=self._tier_modal(
                _("Renewals — by outcome"),
                _("Mark 'Odoo Renewal Outcome' on each renewal SO."),
                _("Outcome"),
                [{"key": "orders", "label": _("Orders"), "format": "integer"}],
                retention_rows),
            chips=[
                {"text": _("Silver ≥ %s%%") % int(SILVER_RETENTION), "tone": ret_tone},
                {"text": _("Gold ≥ %s%%") % int(GOLD_RETENTION),
                 "tone": "wa" if retention_rate is None else ("ok" if ret_gold else "no")},
            ],
        ))

        criteria_rows = [
            {"label": _("① Users (trailing 12m)"), "now": str(trailing_now),
             "silver": _("PASS") if users_silver else _("FAIL"),
             "gold": _("PASS") if users_gold else _("−%s") % gold_user_gap,
             "tones": {"silver": "good" if users_silver else "bad",
                       "gold": "good" if users_gold else "bad"}},
            {"label": _("② Consultants"), "now": str(len(consultants)),
             "silver": _("PASS") if cons_silver else _("FAIL"),
             "gold": _("PASS") if cons_gold else _("−%s") % gold_cons_gap,
             "tones": {"silver": "good" if cons_silver else "bad",
                       "gold": "good" if cons_gold else "bad"}},
            {"label": _("③ Retention"), "now": retention_text,
             "silver": _("PASS") if (retention_rate is not None and ret_silver)
             else (_("no data") if retention_rate is None else _("FAIL")),
             "gold": _("PASS") if ret_gold
             else (_("no data") if retention_rate is None else _("FAIL")),
             "tones": {"silver": "good" if (retention_rate is not None and ret_silver) else "warn",
                       "gold": "good" if ret_gold else "warn"}},
        ]
        next_review = self._tier_next_reviews(today, 1)[0]
        standing_chips = [
            {"text": (_("Silver — SECURE today") if silver_ok
                      else _("Silver — FAILING today")),
             "tone": "ok" if silver_ok else "no"},
        ]
        gold_gaps = []
        if not users_gold:
            gold_gaps.append(_("users"))
        if not cons_gold:
            gold_gaps.append(_("consultants"))
        if not ret_gold:
            gold_gaps.append(_("retention"))
        standing_chips.append(
            {"text": _("Gold ✓") if gold_ok
             else _("Gold — gaps: %s") % ", ".join(gold_gaps),
             "tone": "ok" if gold_ok else "no"})
        if silver_loss_month:
            standing_chips.append(
                {"text": _("Silver at risk by %s") % next(
                    (r.strftime("%d %b %Y") for r in self._tier_next_reviews(today, 8)
                     if r >= silver_loss_month), self._tier_month_label(silver_loss_month)),
                 "tone": "wa"})
        widgets.append(self._tier_kpi(
            "tier_standing", _("Standing"), 1 if silver_ok else 0,
            _("next review · %s") % next_review.strftime("%d %b %Y"),
            _("Definition: current tier verdict across all three criteria "
              "(all must pass; reviews at each SA-quarter start on the "
              "trailing 12 months, one-quarter grace before a downgrade). "
              "Click for the criteria scorecard."),
            value_text=_("Gold") if gold_ok else (_("Silver") if silver_ok else _("At risk")),
            coin=_("Au") if gold_ok else _("Ag"),
            color="#2f9e6b" if silver_ok else "#cf4257",
            modal=self._tier_modal(
                _("Tier criteria — scorecard"), _("All three must hold."),
                _("Criterion"),
                [{"key": "now", "label": _("Today"), "format": "text"},
                 {"key": "silver", "label": _("Silver"), "format": "text"},
                 {"key": "gold", "label": _("Gold"), "format": "text"}],
                criteria_rows),
            chips=standing_chips,
        ))

        # Row 2 -- the alarm banner (worst alert only, mockup style).
        banner = None
        if silver_loss_month:
            loss_review = next((r for r in self._tier_next_reviews(today, 8)
                                if r >= silver_loss_month), silver_loss_month)
            at_loss = self._tier_trailing(actual_cohorts, silver_loss_month)
            banner = {
                "sev": "bad",
                "text": _("Without new closes, trailing-12m users fall from "
                          "%(now)s today to %(at)s by %(month)s — below the "
                          "%(floor)s Silver floor. The %(review)s review is "
                          "the deadline to keep Silver. Fill Expected User "
                          "License on open Odoo deals to see the pipeline "
                          "close this gap.")
                % {"now": trailing_now, "at": at_loss,
                   "month": self._tier_month_label(silver_loss_month),
                   "floor": SILVER_USERS,
                   "review": loss_review.strftime("%d %b %Y")},
            }
        elif not pipeline_dated:
            banner = {
                "sev": "warn",
                "text": _("No open deal carries an Expected User License with "
                          "an Expected Closing date — the forecast line is "
                          "blind. Ask the reps to fill both fields on every "
                          "open Odoo deal."),
            }
        elif not users_gold:
            banner = {
                "sev": "warn",
                "text": _("%(short)s more trailing users and %(cons)s more "
                          "certifications needed for Gold (%(now)s of %(g)s "
                          "users today).")
                % {"short": gold_user_gap, "cons": max(gold_cons_gap, 0),
                   "now": trailing_now, "g": GOLD_USERS},
            }
        if banner:
            widgets.append({
                "id": "tier_banner", "name": _("Tier alert"),
                "type": "banner", "model": "", "mode": "computed",
                "measure": "", "groupby": "", "color": TIER_COLOR,
                "help": "", "info": _(
                    "Definition: the most urgent tier alert, recomputed from "
                    "the rules every time the page loads."),
                "value": 1.0, "format": "integer", "domain": [],
                "points": [], "rows": [], "columns": [], "span": 12,
                "error": False, "sev": banner["sev"], "text": banner["text"],
            })

        # Row 3 -- the hero trend (mockup line chart).
        chart_max = max([GOLD_USERS] + [
            v for p in trend_points
            for v in (p.get("actual"), p.get("committed"), p.get("forecast"))
            if v is not None])
        widgets.append({
            "id": "tier_trend",
            "name": _("Are we holding the tier? 12 months back, 12 forward"),
            "type": "tierline", "model": "crm.lead", "mode": "computed",
            "measure": _("Users"), "groupby": _("Month"), "color": TIER_COLOR,
            "help": "", "info": _(
                "Definition: the tier number over time. Solid line = actual "
                "trailing-12m users; faded = committed roll-off if nothing "
                "new closes; dashed = with pipeline (Expected User License, "
                "counted from the month after expected close). Threshold "
                "lines mark Silver %(s)s and Gold %(g)s. Click a month for "
                "its cohort movements.")
            % {"s": SILVER_USERS, "g": GOLD_USERS},
            "value": float(trailing_now), "format": "integer",
            "domain": [], "points": trend_points, "rows": [], "columns": [],
            "span": 12, "error": False,
            "gold": GOLD_USERS, "silver": SILVER_USERS,
            "max_value": int(chart_max * 1.08) + 1,
            "label_actual": _("Actual"),
            "label_committed": _("Committed roll-off"),
            "label_forecast": _("With pipeline"),
        })

        # Row 4 -- company contribution: stacked bar + three company cards.
        company_colors = {"Mrelate · India": "#7d4b78",
                          "PT Istana · Indonesia": "#2f8f89",
                          "LinkedERP · South Africa": "#4f6bb0",
                          TIER_OTHER_COMPANY: "#64748b"}
        stack_points = []
        for label in [l for _t, l in TIER_COMPANY_TOKENS] + [TIER_OTHER_COMPANY]:
            cohorts = by_company.get(label) or []
            seg_users = sum(c["users"] for c in cohorts)
            if not seg_users:
                continue
            lead_ids = [c["lead_id"] for c in cohorts if c.get("lead_id")]
            stack_points.append({
                "label": label, "value": seg_users,
                "pct": round(seg_users / trailing_now * 100) if trailing_now else 0,
                "color": company_colors[label],
                "domain": self._json_safe([("id", "in", lead_ids)]),
            })
        widgets.append({
            "id": "tier_company_stack",
            "name": _("Who's driving the tier — by company"),
            "type": "tierstack", "model": "crm.lead", "mode": "computed",
            "measure": _("trailing-12m users"), "groupby": _("Company"),
            "color": TIER_COLOR, "help": "", "info": _(
                "Definition: each entity's share of the current trailing-12m "
                "user licences (LinkedERP internal licences count under "
                "LinkedERP). Click a segment for those deals."),
            "value": float(trailing_now), "format": "integer", "domain": [],
            "points": stack_points, "rows": [], "columns": [],
            "span": 12, "error": False,
        })

        for index, (_token, label) in enumerate(TIER_COMPANY_TOKENS):
            cohorts = by_company.get(label) or []
            co_users = sum(c["users"] for c in cohorts)
            share = round(co_users / trailing_now * 100) if trailing_now else 0
            arr = arr_by_company.get(label, 0.0)
            arr_pct = round(arr / arr_target * 100) if arr_target else 0
            company_rows = [{
                "label": c["label"], "users": c["users"],
                "arr": usd_short((c.get("revenue") or 0.0) * factors.get(
                    c.get("company_id"), 1.0)) if c.get("lead_id") else dash_text_placeholder,
                "model": "crm.lead" if c.get("lead_id") else "",
                "domain": self._json_safe([("id", "=", c["lead_id"])]) if c.get("lead_id") else [],
            } for c in sorted(cohorts, key=lambda c: -c["users"])]
            widgets.append({
                "id": "tier_co_%d" % index, "name": label,
                "type": "tiercompany", "model": "crm.lead", "mode": "computed",
                "measure": "", "groupby": "", "color": company_colors[label],
                "help": "", "info": _(
                    "Definition: this company's trailing-12m users and its "
                    "Odoo ARR won this SA financial year (USD at today's "
                    "stored rates) against the %(t)s target. Click for its "
                    "customers.") % {"t": usd_short(arr_target)},
                "value": float(co_users), "format": "integer", "domain": [],
                "points": [], "rows": [], "columns": [], "span": 4,
                "error": False,
                "users": co_users, "share": share,
                "arr_text": usd_short(arr),
                "target_text": usd_short(arr_target),
                "arr_pct": arr_pct,
                "bar_pct": min(arr_pct, 100),
                "tone": "ok" if arr_pct >= 100 else ("wa" if arr_pct >= 60 else "no"),
                "modal_table": self._tier_modal(
                    _("%s — customers & ARR") % label,
                    _("Trailing-12m cohorts and this FY's won value."),
                    _("Customer"),
                    [{"key": "users", "label": _("Users"), "format": "integer"},
                     {"key": "arr", "label": _("ARR (FY)"), "format": "text"}],
                    company_rows),
            })

        # Row 5 -- sales targets (mockup: quarter users, group ARR, IN, ID+SA).
        q_label = _("SA Q from %s") % q_start.strftime("%b %Y")
        widgets.append(self._tier_kpi(
            "tier_q_users", _("New Users · this quarter"), q_users,
            _("%(l)s · target %(t)s") % {"l": q_label, "t": q_target},
            _("Definition: user licences on Odoo deals WON inside the current "
              "SA-financial-year quarter (quarters start Feb / May / Aug / "
              "Nov). Target %(t)s new users per quarter (System Parameter "
              "%(p)s). Click for the quarter's deals.")
            % {"t": q_target, "p": PARAM_Q_TARGET},
            value_text=_("%(n)s / %(t)s") % {"n": q_users, "t": q_target},
            model="crm.lead",
            domain=[("id", "in", [c["lead_id"] for c in q_users_cohorts if c.get("lead_id")])],
            scale={"pos": round(min(q_users / q_target, 1.0) * 100, 1) if q_target else 0,
                   "label": _("%(n)s of %(t)s this quarter") % {"n": q_users, "t": q_target},
                   "marks": [{"pos": 100, "label": _("Target %s") % q_target,
                              "right": True}]},
        ))
        group_target = arr_target * len(TIER_COMPANY_TOKENS)
        widgets.append(self._tier_kpi(
            "tier_arr_group", _("Group Odoo ARR · SA FY"), arr_group,
            _("FY from %s") % fy_start.strftime("%b %Y"),
            _("Definition: value (expected revenue) of Odoo deals won since "
              "the SA financial year started (1 Feb), converted to USD at "
              "today's stored rates. Target = %(per)s per company × 3 "
              "(System Parameter %(p)s). Click for the FY's won deals.")
            % {"per": usd_short(arr_target), "p": PARAM_ARR_TARGET},
            value_text=_("%(a)s / %(t)s")
            % {"a": usd_short(arr_group), "t": usd_short(group_target)},
            model="crm.lead",
            domain=[("id", "in", [c["lead_id"] for c in won
                                  if c["month"] >= _month_start(fy_start)])],
            scale={"pos": round(min(arr_group / group_target, 1.0) * 100, 1) if group_target else 0,
                   "label": _("%(p)s%% of the group target")
                   % {"p": round(arr_group / group_target * 100) if group_target else 0},
                   "marks": [{"pos": 100, "label": _("Target %s") % usd_short(group_target),
                              "right": True}]},
        ))
        arr_in = arr_by_company.get("Mrelate · India", 0.0)
        in_pct = round(arr_in / arr_target * 100) if arr_target else 0
        widgets.append(self._tier_kpi(
            "tier_arr_in", _("Mrelate · India ARR"), arr_in,
            _("target %s") % usd_short(arr_target),
            _("Definition: Mrelate's Odoo ARR won this SA FY (USD at today's "
              "rates) against its %(t)s target. Click for the deals.")
            % {"t": usd_short(arr_target)},
            value_text=usd_short(arr_in),
            model="crm.lead",
            domain=[("id", "in", [c["lead_id"] for c in won
                                  if c["company"] == "Mrelate · India"
                                  and c["month"] >= _month_start(fy_start)])],
            chips=[{"text": "%s%%" % in_pct,
                    "tone": "ok" if in_pct >= 100 else ("wa" if in_pct >= 60 else "no")}],
        ))
        arr_id = arr_by_company.get("PT Istana · Indonesia", 0.0)
        arr_za = arr_by_company.get("LinkedERP · South Africa", 0.0)
        idza = arr_id + arr_za
        idza_target = arr_target * 2
        idza_pct = round(idza / idza_target * 100) if idza_target else 0
        widgets.append(self._tier_kpi(
            "tier_arr_idza", _("Indonesia + SA ARR"), idza,
            _("PT Istana %(i)s · LinkedERP %(z)s")
            % {"i": usd_short(arr_id), "z": usd_short(arr_za)},
            _("Definition: PT Istana's and LinkedERP's combined Odoo ARR won "
              "this SA FY against their %(t)s combined target. Click for the "
              "deals.") % {"t": usd_short(idza_target)},
            value_text=_("%(a)s / %(t)s")
            % {"a": usd_short(idza), "t": usd_short(idza_target)},
            model="crm.lead",
            domain=[("id", "in", [c["lead_id"] for c in won
                                  if c["company"] in ("PT Istana · Indonesia",
                                                      "LinkedERP · South Africa")
                                  and c["month"] >= _month_start(fy_start)])],
            chips=[{"text": "%s%%" % idza_pct,
                    "tone": "ok" if idza_pct >= 100 else ("wa" if idza_pct >= 60 else "no")}],
        ))

        # Row 6 -- pipeline driver + roll-off cliff tables (mockup pair).
        pipe_rows = [{
            "label": c["label"],
            "users": c["users"],
            "close": c["deadline"].strftime("%b %Y") if c.get("deadline") else missing_text,
            "counts": self._tier_month_label(c["month"]) if c.get("month") else dash_text_placeholder,
            "model": "crm.lead",
            "domain": self._json_safe([("id", "=", c["lead_id"])]),
            "tones": {} if c.get("month") else {"close": "bad"},
        } for c in sorted(pipeline, key=lambda c: (c.get("month") or date.max))]
        widgets.append({
            "id": "tier_pipeline", "name": _("Pipeline forecast driver"),
            "type": "matrix", "model": "crm.lead", "mode": "computed",
            "measure": _("Records"), "groupby": _("Opportunity"),
            "color": TIER_COLOR, "help": "",
            "info": _(
                "Definition: open deals whose Expected User License feeds the "
                "forecast line. Each adds its users to the trailing count "
                "from the month after its Expected Closing, for 12 months. "
                "Click a row for the deal."),
            "value": float(sum(c["users"] for c in pipeline)), "format": "integer",
            "domain": self._json_safe(
                [("id", "in", [c["lead_id"] for c in pipeline])]),
            "points": [], "rows": pipe_rows,
            "columns": [
                {"key": "users", "label": _("Exp. users"), "format": "integer"},
                {"key": "close", "label": _("Exp. close"), "format": "text"},
                {"key": "counts", "label": _("Counts from"), "format": "text"}],
            "span": 6, "error": False, "compact": True,
        })

        rolloff_rows = []
        for month in months:
            if month <= this_month or month > _month_add(this_month, 12):
                continue
            expiring = [c for c in actual_cohorts
                        if c.get("month") and _month_add(c["month"], 12) == month]
            if not expiring:
                continue
            off = sum(c["users"] for c in expiring)
            lead_ids = [c["lead_id"] for c in expiring if c.get("lead_id")]
            rolloff_rows.append({
                "label": self._tier_month_label(month),
                "off": -off,
                "after": self._tier_trailing(actual_cohorts, month),
                "who": ", ".join(sorted(c["label"] for c in expiring))[:60],
                "model": "crm.lead" if lead_ids else "",
                "domain": self._json_safe([("id", "in", lead_ids)]),
                "tones": {"off": "bad" if off >= 40 else "warn"},
            })
        widgets.append({
            "id": "tier_rolloff", "name": _("Licences rolling off — the cliff"),
            "type": "matrix", "model": "crm.lead", "mode": "computed",
            "measure": _("Records"), "groupby": _("Month"),
            "color": "#cf4257", "help": "",
            "info": _(
                "Definition: cohorts reaching the end of their 12-month "
                "counting window — what pulls the trailing number down. "
                "Click a row for the expiring deals."),
            "value": float(len(rolloff_rows)), "format": "integer",
            "domain": [], "points": [], "rows": rolloff_rows,
            "columns": [
                {"key": "off", "label": _("Rolls off"), "format": "integer"},
                {"key": "after", "label": _("Trailing after"), "format": "integer"},
                {"key": "who", "label": _("Cohort"), "format": "text"}],
            "span": 6, "error": False, "compact": True,
        })

        # Row 7 -- SA-quarter review checkpoint tiles (mockup q-boxes).
        q_points = []
        for review in self._tier_next_reviews(today, 4):
            review_month = _month_start(review)
            fy_q = SA_QUARTER_MONTHS.index(review.month) + 1
            projected = self._tier_trailing(actual_cohorts, _month_add(review_month, -1))
            with_pipe = projected + self._tier_trailing(
                pipeline_dated, _month_add(review_month, -1))
            below = projected < SILVER_USERS
            if projected >= GOLD_USERS:
                status = _("Gold ✓")
            elif not below:
                status = _("Silver ✓ · Gold −%s") % (GOLD_USERS - projected)
            else:
                status = _("Silver ✗ — below %s") % SILVER_USERS
            q_points.append({
                "label": _("%(d)s · Q%(q)s") % {"d": review.strftime("%d %b %Y"), "q": fy_q},
                "value": projected,
                "status": status,
                "tone": "no" if below else "ok",
                "alarm": below,
                "modal_table": self._tier_modal(
                    _("Review %s — projection") % review.strftime("%d %b %Y"),
                    _("Trailing window ending the month before the review."),
                    _("Basis"),
                    [{"key": "users", "label": _("Users"), "format": "integer"}],
                    [{"label": _("Committed only (nothing new closes)"),
                      "users": projected},
                     {"label": _("With pipeline forecast"), "users": with_pipe},
                     {"label": _("Silver floor"), "users": SILVER_USERS},
                     {"label": _("Gold bar"), "users": GOLD_USERS}]),
            })
        widgets.append({
            "id": "tier_reviews",
            "name": _("Review checkpoints · SA quarters (Feb → Jan)"),
            "type": "qtiles", "model": "", "mode": "computed",
            "measure": "", "groupby": _("Review"), "color": TIER_COLOR,
            "help": "", "info": _(
                "Definition: the next four SA-quarter reviews with the "
                "trailing count projected to each date, assuming nothing new "
                "closes (click a tile for the with-pipeline projection). "
                "One-quarter grace applies before a downgrade takes effect."),
            "value": float(len(q_points)), "format": "integer", "domain": [],
            "points": q_points, "rows": [], "columns": [],
            "span": 12, "error": False,
        })

        return widgets
