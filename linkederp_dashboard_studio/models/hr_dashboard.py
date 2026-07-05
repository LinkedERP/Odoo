import re
from datetime import timedelta

from odoo import fields, models, _

PEOPLE_DASHBOARD_NAME = "Aurika People Dashboard"

# Leftover payroll test/dummy employee records that must never count as people.
PEOPLE_TEST_PAT = re.compile(r"zz_uat|dummy|^test\b|\btest\b", re.IGNORECASE)

# Studio / standard hr.employee fields (skip gracefully if absent).
PEOPLE_JOIN_FIELD = "x_studio_date_of_joining"
PEOPLE_SEX_FIELD = "sex"

# Story thresholds (tunable).
PEOPLE_CONCENTRATION_ALERT = 35.0   # a department over this % of people = risk
PEOPLE_ATTRITION_CONCERN = 15.0     # exits over this % of headcount = concern

# Cost section — classify operating-expense accounts into "people cost" by
# NAME (tunable, like the Finance dashboard's EBITDA account rules). Staff =
# own payroll; subcontractors = outsourced delivery ("Partners" here).
PEOPLE_STAFF_PAT = re.compile(
    r"salar|payroll|\bpaye\b|\bfte\b|\bwage|staff|personnel|\bctc\b", re.I)
PEOPLE_SUB_PAT = re.compile(
    r"partner|subcontract|contractor|freelanc|associate|outsourc", re.I)
PEOPLE_IC_ACCOUNT_PAT = re.compile(r"^ic\b", re.I)
PEOPLE_MONTHS = 12  # annualise a monthly wage

PEOPLE_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

TEAL = "#0f6b74"
GREEN = "#0f7a52"
RED = "#c0392f"
AMBER = "#b45309"


class LinkederpDashboardPeople(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_people_dashboard()

    def _ensure_people_dashboard(self):
        if self._ensure_dashboard_name(PEOPLE_DASHBOARD_NAME, []):
            return
        if "hr.employee" not in self.env:
            return
        self.create({
            "name": PEOPLE_DASHBOARD_NAME,
            "sequence": 80,
            "bucket": "management",
            "description": _(
                "The MDs' people cockpit: headcount (by person, not record), "
                "gender, growth, attrition, tenure and time off across all "
                "companies — with a board-ready story strip. Cost/salary is a "
                "separate phase."),
            "color": TEAL,
        })

    def _is_people_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == PEOPLE_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    def _people_company_options(self):
        return [{"id": c.id, "name": c.name}
                for c in self.env["res.company"].search([], order="name")]

    def _people_selected_company(self, filters=False):
        filters = filters or {}
        try:
            value = int(filters.get("people_company_id") or 0)
        except (TypeError, ValueError):
            value = 0
        if value in {c["id"] for c in self._people_company_options()}:
            return value
        return 0

    def _people_selected_period(self, filters=False):
        filters = filters or {}
        value = str(filters.get("people_period") or "")
        return value if value in ("12m", "ytd") else "12m"

    def _people_filter_options(self, filters=False):
        return {
            "enabled": True,
            "company": self._people_selected_company(filters) or "",
            "companies": self._people_company_options(),
            "period": self._people_selected_period(filters),
            "periods": [
                {"value": "12m", "label": _("Last 12 months")},
                {"value": "ytd", "label": _("This year")},
            ],
        }

    def _people_period_window(self, period, today):
        """(start, end, prior_start) — prior_start begins the equal-length
        window immediately before `start` (for vs-prior-period deltas)."""
        end = today
        if period == "ytd":
            start = today.replace(month=1, day=1)
        else:
            start = today - timedelta(days=365)
        length = (end - start).days or 1
        return start, end, start - timedelta(days=length)

    def _people_period_label(self, period):
        return _("this year") if period == "ytd" else _("last 12 months")

    # ------------------------------------------------------------------
    # Person model — "count people, not records"
    # ------------------------------------------------------------------
    @staticmethod
    def _people_norm(name):
        return re.sub(r"\s*\([A-Z]{2}\)\s*$", "",
                      re.sub(r"\s+", " ", name or "")).strip().lower()

    def _people_is_test(self, name):
        return bool(PEOPLE_TEST_PAT.search(name or ""))

    def _people_collect(self, company_id):
        """Build the person-deduped population plus the raw movement/leave
        rows every widget needs. `company_id` = 0 means the group."""
        today = fields.Date.context_today(self)
        Employee = self.env["hr.employee"]
        efields = Employee._fields
        has_join = PEOPLE_JOIN_FIELD in efields
        has_sex = PEOPLE_SEX_FIELD in efields
        has_wage = "wage" in efields
        companies = self.env["res.company"].search([])
        company_names = {c.id: c.name for c in companies}

        read_fields = ["name", "user_id", "company_id", "department_id"]
        if has_join:
            read_fields.append(PEOPLE_JOIN_FIELD)
        if has_sex:
            read_fields.append(PEOPLE_SEX_FIELD)
        if has_wage:
            read_fields.append("wage")

        raw = Employee.search_read([("active", "=", True)], read_fields)
        real = [e for e in raw if not self._people_is_test(e["name"])]
        test_records = [e for e in raw if self._people_is_test(e["name"])]

        # user_id present on ANY record for a normalized name → that name's user
        name_user = {}
        for e in real:
            if e["user_id"]:
                name_user[self._people_norm(e["name"])] = e["user_id"][0]

        # user home company (default company)
        user_ids = sorted({e["user_id"][0] for e in real if e["user_id"]})
        home = {}
        if user_ids:
            for u in self.env["res.users"].browse(user_ids):
                home[u.id] = u.company_id.id

        def identity(e):
            if e["user_id"]:
                return ("u", e["user_id"][0])
            nm = self._people_norm(e["name"])
            if nm in name_user:
                return ("u", name_user[nm])
            return ("n", nm)

        # For each person keep the DEFAULT-company record, else any; prefer a
        # record that actually carries the attribute (dept/sex).
        persons = {}
        for e in real:
            pid = identity(e)
            cid = e["company_id"][0] if e["company_id"] else 0
            is_home = (pid[0] == "u" and home.get(pid[1]) == cid)
            cur = persons.get(pid)
            better = (
                cur is None
                or (is_home and not cur["_home"])
                or (not cur.get("dept") and e["department_id"])
                or (has_sex and not cur.get("sex") and e.get(PEOPLE_SEX_FIELD))
            )
            if better:
                persons[pid] = {
                    "pid": pid,
                    "emp_ids": (cur["emp_ids"] if cur else []) + [e["id"]],
                    "name": self._people_norm(e["name"]).title(),
                    "company_id": (home.get(pid[1]) if pid[0] == "u"
                                   and home.get(pid[1]) else cid),
                    "dept": (e["department_id"][1]
                             if e["department_id"] else False),
                    "dept_id": (e["department_id"][0]
                                if e["department_id"] else False),
                    "join": e.get(PEOPLE_JOIN_FIELD) if has_join else False,
                    "sex": e.get(PEOPLE_SEX_FIELD) if has_sex else False,
                    # Monthly wage in the record's company currency; 0 until
                    # entered. Converted to USD per home company in the cost
                    # section (never hardcoded to one currency/country).
                    "wage": e.get("wage") if has_wage else 0.0,
                    "_home": is_home,
                }
            else:
                persons[pid]["emp_ids"].append(e["id"])

        # scope to a single company (home company) if asked
        people = list(persons.values())
        if company_id:
            people = [p for p in people if p["company_id"] == company_id]

        # Hygiene reflects the SCOPED view (so counts + drill-downs match the
        # headline and the "X only" caption).
        no_login = sum(1 for p in people if p["pid"][0] == "n")
        no_dept = sum(1 for p in people if not p["dept_id"])
        test_scoped = [e for e in test_records
                       if not company_id
                       or (e["company_id"] and e["company_id"][0] == company_id)]

        # departed people (archived) with a departure date — dedup by identity
        dep_fields = ["name", "user_id", "company_id", "departure_date",
                      "departure_reason_id"]
        departed = {}
        for e in Employee.with_context(active_test=False).search_read(
                [("departure_date", "!=", False)], dep_fields):
            if self._people_is_test(e["name"]):
                continue
            cid = e["company_id"][0] if e["company_id"] else 0
            if company_id:
                # Same rule as `people`: a person belongs to their user's
                # HOME company when known, else the record's company — so the
                # attrition numerator and denominator share one definition
                # (otherwise a small subsidiary can print >100%).
                uid = e["user_id"][0] if e["user_id"] else None
                person_company = home.get(uid) if (uid and home.get(uid)) else cid
                if person_company != company_id:
                    continue
            key = (("u", e["user_id"][0]) if e["user_id"]
                   else ("n", self._people_norm(e["name"])))
            d = str(e["departure_date"])[:10]
            dedup = (key, d)
            if dedup in departed:
                continue
            departed[dedup] = {
                "emp_id": e["id"],
                "date": d,
                "reason": (e["departure_reason_id"][1]
                           if e["departure_reason_id"] else _("Not recorded")),
                "reason_id": (e["departure_reason_id"][0]
                              if e["departure_reason_id"] else False),
            }

        # validated leave (widest window = 13 months back)
        leaves = []
        if "hr.leave" in self.env:
            floor = str(today - timedelta(days=400))
            lv_domain = [("state", "=", "validate"),
                         ("date_from", ">=", floor)]
            if company_id:
                lv_domain.append(("employee_id.company_id", "=", company_id))
            for l in self.env["hr.leave"].search_read(
                    lv_domain, ["number_of_days", "holiday_status_id",
                                "date_from"]):
                leaves.append({
                    "id": l["id"],
                    "days": l["number_of_days"] or 0.0,
                    "type": (l["holiday_status_id"][1]
                             if l["holiday_status_id"] else _("Other")),
                    "type_id": (l["holiday_status_id"][0]
                                if l["holiday_status_id"] else False),
                    "date": str(l["date_from"])[:10],
                })

        return {
            "today": today,
            "companies": [(c.id, c.name) for c in companies],
            "company_names": company_names,
            "people": people,
            "all_people_count": len(persons),
            "departed": list(departed.values()),
            "leaves": leaves,
            "has_join": has_join,
            "has_sex": has_sex,
            "hygiene": {"test": len(test_scoped),
                        "test_ids": [e["id"] for e in test_scoped],
                        "no_login": no_login, "no_dept": no_dept},
        }

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _people_safe_date(value):
        """Parse a date that may come from a Studio Char field holding a
        non-ISO or free-text value — Odoo 19's `to_date` RAISES on garbage,
        so never let a single bad joining date crash the whole dashboard."""
        if not value:
            return None
        try:
            return fields.Date.to_date(str(value)[:10])
        except (ValueError, TypeError):
            return None

    def _people_years(self, join, today):
        j = self._people_safe_date(join)
        return (today - j).days / 365.25 if j else None

    def _people_hires(self, people, start, end):
        rows = []
        for p in people:
            j = self._people_safe_date(p["join"])
            if j and start <= j <= end:
                rows.append(p)
        return rows

    def _people_exits(self, departed, start, end):
        s, e = str(start), str(end)
        return [d for d in departed if s <= d["date"] <= e]

    def _people_median(self, values):
        vals = sorted(v for v in values if v is not None)
        if not vals:
            return 0.0
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2

    def _people_delta(self, current, prior):
        if not prior:
            return False
        pct = round((current - prior) / abs(prior) * 100)
        if pct >= 0:
            return {"text": "▲ %d%%" % pct, "dir": "up"}
        return {"text": "▼ %d%%" % abs(pct), "dir": "down"}

    # ------------------------------------------------------------------
    # Widget primitives
    # ------------------------------------------------------------------
    def _people_kpi(self, wid, name, value, fmt, caption, color, help_text,
                    model="", domain=None, hero=False, span=3, delta=False,
                    split=False, value_text=False, points=None,
                    modal_table=False):
        return {
            "id": wid, "name": name, "type": "kpi", "model": model,
            "mode": "computed", "measure": caption, "groupby": "",
            "color": color, "help": help_text, "value": float(value),
            "format": fmt, "domain": self._json_safe(domain or []),
            "points": points or [], "rows": [], "columns": [], "span": span,
            "error": False, "hero": hero, "delta": delta, "split": split,
            "value_text": value_text, "scale": False,
            "modal_table": modal_table,
        }

    def _people_sechead(self, wid, name):
        return {"id": wid, "name": name, "type": "sechead", "model": "",
                "mode": "computed", "measure": "", "groupby": "", "color": TEAL,
                "help": "", "value": 0.0, "format": "integer", "domain": [],
                "points": [], "rows": [], "columns": [], "span": 12,
                "error": False}

    def _people_bar(self, wid, name, points, help_text, measure, groupby,
                    model="hr.employee", span=6):
        return {"id": wid, "name": name, "type": "bar", "model": model,
                "mode": "computed", "measure": measure, "groupby": groupby,
                "color": TEAL, "help": help_text, "value": float(len(points)),
                "format": "integer", "domain": [], "points": points,
                "rows": [], "columns": [], "span": span, "error": False,
                "tall": True}

    def _people_story(self, items):
        return {"id": "people_story", "name": _("The Story for the Board"),
                "type": "story", "model": "", "mode": "computed",
                "measure": "", "groupby": "", "color": TEAL,
                "help": _("Written automatically from the numbers — your "
                          "opening script."), "value": float(len(items)),
                "format": "integer", "domain": [], "points": [], "rows": [],
                "columns": [], "span": 12, "error": False, "items": items}

    # ------------------------------------------------------------------
    # Board story
    # ------------------------------------------------------------------
    def _people_story_items(self, headcount, comp_split, net, hires, exits,
                            top_dept, top_dept_n, sex_counts, median_tenure,
                            period_label):
        items = []
        countries = sum(1 for _c, n in comp_split if n)
        items.append({
            "tone": "good" if net >= 0 else "watch",
            "headline": _("A team of %s across %s %s.") % (
                headcount, countries,
                _("countries") if countries != 1 else _("country")),
            "text": _("Net %(sign)s%(net)s over %(period)s — %(inn)s joined, "
                      "%(out)s left.") % {
                "sign": "+" if net >= 0 else "−", "net": abs(net),
                "period": period_label, "inn": hires, "out": exits},
        })
        if headcount and exits >= headcount * PEOPLE_ATTRITION_CONCERN / 100.0:
            items.append({
                "tone": "concern",
                "headline": _("Retention is the watch-item."),
                "text": _("%s people left %s — worth understanding; the 2025 "
                          "figure may be inflated by a data clean-up.") % (
                    exits, period_label),
            })
        if headcount and top_dept and top_dept_n / headcount * 100.0 \
                > PEOPLE_CONCENTRATION_ALERT:
            items.append({
                "tone": "watch",
                "headline": _("Concentrated in one team."),
                "text": _("%(dept)s is %(pct)s%% of everyone — deep expertise, "
                          "but key-person risk.") % {
                    "dept": top_dept,
                    "pct": round(top_dept_n / headcount * 100)},
            })
        male = sex_counts.get("male", 0)
        female = sex_counts.get("female", 0)
        if headcount and (male or female):
            majority = _("men") if male >= female else _("women")
            share = round(max(male, female) / headcount * 100)
            items.append({
                "tone": "watch",
                "headline": _("Male-skewed & young.") if male >= female
                else _("Balanced, young team."),
                "text": _("%(share)s%% %(majority)s, and median tenure "
                          "%(ten)s years — mind the balance and the thin "
                          "veteran bench.") % {
                    "share": share, "majority": majority,
                    "ten": round(median_tenure, 1)},
            })
        return items[:4]

    # ------------------------------------------------------------------
    # The dashboard
    # ------------------------------------------------------------------
    def _people_dashboard_widgets(self, date_from=False, date_to=False,
                                  filters=False):
        if "hr.employee" not in self.env:
            return [self._people_kpi(
                "people_empty", PEOPLE_DASHBOARD_NAME, 0, "integer",
                _("HR is not installed."), "#64748b",
                _("Install Employees to populate this dashboard."), span=12)]

        options = self._people_filter_options(filters)
        company_id = options["company"] or 0
        period = options["period"]
        data = self._people_collect(company_id)
        today = data["today"]
        start, end, prior_start = self._people_period_window(period, today)
        period_label = self._people_period_label(period)
        people = data["people"]
        headcount = len(people)

        company_name = ""
        if company_id:
            company_name = dict(data["companies"]).get(company_id, "")
        scope_note = (_("%s only.") % company_name if company_id
                      else _("All companies, counted by person."))

        # ---- movement ----
        hires = self._people_hires(people, start, end)
        exits = self._people_exits(data["departed"], start, end)
        prior_hires = self._people_hires(people, prior_start, start)
        prior_exits = self._people_exits(data["departed"], prior_start, start)
        net = len(hires) - len(exits)
        avg_hc = (headcount + (headcount - len(hires) + len(exits))) / 2.0
        attrition = round(len(exits) / avg_hc * 100, 1) if avg_hc else 0.0

        # ---- gender ----
        sex_counts = {}
        for p in people:
            sex_counts[p["sex"] or "unset"] = sex_counts.get(
                p["sex"] or "unset", 0) + 1
        male = sex_counts.get("male", 0)
        female = sex_counts.get("female", 0)
        unset = sex_counts.get("unset", 0)
        male_pct = round(male / headcount * 100) if headcount else 0

        # ---- company split ----
        comp_split = []
        for cid, cname in data["companies"]:
            n = sum(1 for p in people if p["company_id"] == cid)
            if n:
                comp_split.append((cname, n))
        comp_split.sort(key=lambda x: -x[1])
        comp_caption = " · ".join("%s %s" % (n.split()[0], c)
                                  for n, c in comp_split) or _("—")

        # ---- tenure ----
        tenures = [self._people_years(p["join"], today) for p in people]
        median_tenure = self._people_median(tenures)
        avg_tenure = (sum(t for t in tenures if t is not None)
                      / max(1, sum(1 for t in tenures if t is not None)))
        longest = max((t for t in tenures if t is not None), default=0.0)

        # ---- departments ----
        dept = {}
        for p in people:
            key = p["dept"] or _("No department")
            entry = dept.setdefault(key, {"n": 0, "id": p["dept_id"]})
            entry["n"] += 1
        dept_sorted = sorted(dept.items(), key=lambda kv: -kv[1]["n"])
        top_dept, top_dept_n = (dept_sorted[0][0], dept_sorted[0][1]["n"]) \
            if dept_sorted else ("", 0)

        # ---- header ----
        chips = {
            "id": "people_header", "name": _("Context"), "type": "chips",
            "model": "", "mode": "computed", "measure": "", "groupby": "",
            "color": TEAL, "help": "", "value": 0.0, "format": "integer",
            "domain": [], "points": [], "rows": [], "columns": [], "span": 12,
            "error": False,
            "chips": [
                {"icon": "fa-users", "tone": "accent",
                 "text": (company_name or _("All companies (group)"))},
                {"icon": "fa-calendar", "tone": "",
                 "text": _("Movement window: %s") % period_label},
                {"icon": "fa-user", "tone": "",
                 "text": _("Counted by person (Odoo user), not by record")},
            ],
        }

        story = self._people_story(self._people_story_items(
            headcount, comp_split, net, len(hires), len(exits),
            top_dept, top_dept_n, sex_counts, median_tenure, period_label))

        active_emp_ids = [eid for p in people for eid in p["emp_ids"]]
        hero = [
            self._people_kpi(
                "people_headcount", _("Headcount"), headcount, "integer",
                _("people · %s") % comp_caption, TEAL,
                _("Distinct people (by Odoo user), not employee records; "
                  "test/dummy records excluded. Click for the list.") + " "
                + scope_note,
                model="hr.employee",
                domain=[("id", "in", active_emp_ids)],
                hero=True, delta=self._people_delta(headcount, headcount - net)),
            self._people_kpi(
                "people_gender", _("Gender Mix"), male_pct, "percent",
                _("%(m)s men · %(f)s women · %(u)s unrecorded") % {
                    "m": male, "f": female, "u": unset}, "#2a92b8",
                _("Share of the team that is male (from the employee sex "
                  "field). %s unrecorded — worth filling in.") % unset + " "
                + scope_note,
                hero=True,
                split=[
                    {"pct": male_pct, "color": "#2a92b8", "label": _("Men")},
                    {"pct": round(female / headcount * 100) if headcount else 0,
                     "color": "#e0a13a", "label": _("Women")},
                    {"pct": round(unset / headcount * 100) if headcount else 0,
                     "color": "#9fb2bd", "label": _("Unset")},
                ]),
            self._people_kpi(
                "people_net", _("Net Change · %s") % period_label, net,
                "integer",
                _("%(inn)s joined · %(out)s left") % {
                    "inn": len(hires), "out": len(exits)},
                GREEN if net >= 0 else RED,
                _("Joiners minus leavers over the window. Click for who "
                  "joined.") + " " + scope_note,
                model="hr.employee",
                domain=[("id", "in", [p["emp_ids"][0] for p in hires])],
                hero=True, span=2,
                value_text=("+%s" % net if net >= 0 else "−%s" % abs(net)),
                delta=self._people_delta(
                    len(hires) - len(exits),
                    len(prior_hires) - len(prior_exits))),
            self._people_kpi(
                "people_attrition", _("Attrition · %s") % period_label,
                attrition, "percent",
                _("%s left — validate the 2025 spike") % len(exits), RED,
                _("Leavers ÷ average headcount over the window. Flagged: 2025 "
                  "shows an unusual exit spike that may be back-dated "
                  "historical data, not real churn.") + " " + scope_note,
                model="hr.employee",
                domain=self._json_safe([
                    ("id", "in", [d["emp_id"] for d in exits])]),
                hero=True, span=2, value_text="≈ %s%% ⚠" % round(attrition),
                delta=self._people_delta(
                    len(exits), len(prior_exits))),
            self._people_kpi(
                "people_tenure", _("Median Tenure"), round(median_tenure, 1),
                "number",
                _("avg %(a)s · longest %(l)s yrs") % {
                    "a": round(avg_tenure, 1), "l": round(longest)}, TEAL,
                _("Years since joining, middle value. A young median means a "
                  "fast-grown team.") + " " + scope_note,
                hero=True, span=2, value_text=_("%s yrs") % round(median_tenure, 1)),
        ]

        # ---- department bar ----
        dept_points = [{
            "label": name,
            "value": entry["n"],
            "color": TEAL,
            "domain": self._json_safe(
                [("department_id", "=", entry["id"]), ("active", "=", True)]
                if entry["id"] else
                [("department_id", "=", False), ("active", "=", True)]),
        } for name, entry in dept_sorted]
        dept_bar = self._people_bar(
            "people_departments", _("Where Everyone Sits"), dept_points,
            _("Headcount by department (by person). Click a row for the "
              "team.") + " " + scope_note,
            _("People"), _("Department"))

        # ---- tenure distribution ----
        buckets = [("< 2 yrs", 0, 2), ("2–5 yrs", 2, 5),
                   ("5–10 yrs", 5, 10), ("10+ yrs", 10, 999)]
        ten_points = []
        shades = ["#0f6b74", "#1a7f89", "#3a97a0", "#6bb3ba"]
        for i, (label, lo, hi) in enumerate(buckets):
            n = sum(1 for t in tenures if t is not None and lo <= t < hi)
            ten_points.append({"label": label, "value": n,
                               "color": shades[i], "domain": [],
                               "detail": None})
        tenure_col = {
            "id": "people_tenure_dist", "name": _("How Long People Stay"),
            "type": "column", "model": "", "mode": "computed",
            "measure": _("People"), "groupby": _("Tenure"), "color": TEAL,
            "help": _("Distribution of tenure across the team.") + " "
            + scope_note,
            "value": float(headcount), "format": "integer", "domain": [],
            "points": ten_points, "rows": [], "columns": [], "span": 6,
            "error": False, "target": 0.0, "tall": True}

        # ---- joins vs exits by year (columns2: a=left/red, b=joined/green) ----
        years = list(range(today.year - 5, today.year + 1))
        hire_by_year = {y: [] for y in years}
        exit_by_year = {y: [] for y in years}
        for p in people:
            j = self._people_safe_date(p["join"])
            if j and j.year in hire_by_year:
                hire_by_year[j.year].append(p["emp_ids"][0])
        for d in data["departed"]:
            y = int(d["date"][:4])
            if y in exit_by_year:
                exit_by_year[y].append(d["emp_id"])
        movement_points = [{
            "label": "'%02d" % (y % 100),
            "a": len(exit_by_year[y]),
            "b": len(hire_by_year[y]),
            "domain": self._json_safe([("id", "in", exit_by_year[y])]),
            "domain_b": self._json_safe([("id", "in", hire_by_year[y])]),
        } for y in years]
        movement = {
            "id": "people_movement", "name": _("Joined vs Left, by Year"),
            "type": "columns2", "model": "hr.employee", "mode": "computed",
            "measure": _("People"), "groupby": _("Year"), "color": TEAL,
            "help": _("Green = joined, red = left. Click a bar for the "
                      "people.") + " " + scope_note,
            "value": float(sum(len(v) for v in hire_by_year.values())),
            "format": "integer",
            "domain": self._json_safe([("id", "in", active_emp_ids)]),
            "points": movement_points, "rows": [], "columns": [], "span": 6,
            "error": False, "label_a": _("Left"), "label_b": _("Joined")}

        # ---- why people leave ----
        reasons = {}
        for d in exits:
            entry = reasons.setdefault(d["reason"],
                                       {"n": 0, "ids": [], "id": d["reason_id"]})
            entry["n"] += 1
            entry["ids"].append(d["emp_id"])
        reason_sorted = sorted(reasons.items(), key=lambda kv: -kv[1]["n"])
        reason_points = [{
            "label": name,
            "value": entry["n"],
            "color": RED if i == 0 else AMBER if i == 1 else TEAL,
            "domain": self._json_safe([("id", "in", entry["ids"])]),
        } for i, (name, entry) in enumerate(reason_sorted)]
        reasons_bar = self._people_bar(
            "people_reasons", _("Why People Leave"), reason_points,
            _("Recorded exit reasons over %s. Click a row for who.")
            % period_label + " " + scope_note,
            _("Leavers"), _("Reason"))

        # ---- time off ----
        period_leaves = [l for l in data["leaves"]
                         if str(start) <= l["date"] <= str(end)]
        total_days = sum(l["days"] for l in period_leaves)
        by_type = {}
        for l in period_leaves:
            entry = by_type.setdefault(l["type"], {"days": 0.0, "ids": [],
                                                   "id": l["type_id"]})
            entry["days"] += l["days"]
            entry["ids"].append(l["id"])
        type_sorted = sorted(by_type.items(), key=lambda kv: -kv[1]["days"])[:5]
        leave_points = [{
            "label": name,
            "value": round(entry["days"]),
            "color": AMBER if "sick" in name.lower() else TEAL,
            "domain": self._json_safe([("id", "in", entry["ids"])]),
        } for name, entry in type_sorted]
        working_days = max(1, (end - start).days / 365.25 * 250)
        absence = round(total_days / (headcount * working_days) * 100, 1) \
            if headcount else 0.0
        leave_bar = self._people_bar(
            "people_leave", _("Time Off & Wellbeing"), leave_points,
            _("Approved leave over %(p)s — %(d)s days across %(n)s requests, "
              "≈%(a)s%% absence. Click a type for the entries.") % {
                "p": period_label, "d": round(total_days),
                "n": len(period_leaves), "a": absence} + " " + scope_note,
            _("Days"), _("Leave type"), model="hr.leave")

        # ---- data hygiene ----
        hyg = data["hygiene"]
        nodept_domain = [("active", "=", True), ("department_id", "=", False)]
        if company_id:
            nodept_domain.append(("company_id", "=", company_id))
        hygiene_rows = [
            {"label": _("Test / dummy records still active"),
             # Exact ids so the drill-down matches the count (the name
             # patterns can't be expressed as one Odoo domain).
             "model": "hr.employee" if hyg["test"] else "",
             "domain": self._json_safe([("id", "in", hyg["test_ids"])]),
             "val": "%s" % hyg["test"],
             "status": _("archive them") if hyg["test"] else _("clean"),
             "tones": {"status": "warn" if hyg["test"] else "good"}},
            {"label": _("Real people with no Odoo login"),
             "domain": [], "val": "%s" % hyg["no_login"],
             "status": _("give a login") if hyg["no_login"] else _("clean"),
             "tones": {"status": "warn" if hyg["no_login"] else "good"}},
            {"label": _("Active roles with no department"),
             "model": "hr.employee" if hyg["no_dept"] else "",
             "domain": self._json_safe(nodept_domain),
             "val": "%s" % hyg["no_dept"],
             "status": _("assign") if hyg["no_dept"] else _("clean"),
             "tones": {"status": "warn" if hyg["no_dept"] else "good"}},
            {"label": _("Wages entered in Odoo (for the cost phase)"),
             "domain": [], "val": _("0 of %s") % headcount,
             "status": _("Phase C"),
             "tones": {"status": "bad"}},
        ]
        hygiene = self._people_matrix(
            "people_hygiene", _("Data Hygiene"), hygiene_rows,
            [{"key": "val", "label": _("Today"), "format": "money"},
             {"key": "status", "label": _("Status"), "format": "text"}],
            _("The count is only as good as the records behind it — the same "
              "idea as the Finance housekeeping row.") + " " + scope_note,
            _("Check"), span=6)

        widgets = [chips, story] + hero + [
            self._people_sechead("people_sec_who", _("Who we are")),
            dept_bar, tenure_col,
            self._people_sechead("people_sec_move", _("Coming & going")),
            movement, reasons_bar,
            self._people_sechead("people_sec_day", _("Day to day")),
            leave_bar, hygiene,
        ]
        widgets += self._people_cost_widgets(
            data, company_id, start, end, headcount, scope_note)
        return widgets

    # ------------------------------------------------------------------
    # Cost & compensation (Phase C — generic, group USD, never India-only)
    # ------------------------------------------------------------------
    def _people_cost_ledger(self, company_id, start, end):
        """People-cost split of operating expense + revenue over [start,end],
        USD, group-view IC-excluded. Reuses the Finance engine so the People
        and Finance dashboards can never disagree on the account rules."""
        if "account.move.line" not in self.env:
            return None
        usd = self._mgmt_usd()
        today = fields.Date.context_today(self)
        companies = self.env["res.company"].search([])
        factors = self._fin_usd_factors(usd, today, companies)
        ic_partners = set(companies.mapped("partner_id").ids)
        buckets, names, _special = self._fin_account_buckets()
        op_ids = [aid for aid, b in buckets.items() if b in ("dc", "opex")]
        rev_ids = {aid for aid, b in buckets.items() if b in ("rev", "oth")}
        staff_ids, sub_ids = set(), set()
        for aid in op_ids:
            nm = names.get(aid, "")
            if PEOPLE_SUB_PAT.search(nm):
                sub_ids.add(aid)
            elif PEOPLE_STAFF_PAT.search(nm):
                staff_ids.add(aid)
        domain = [("account_id", "in", op_ids + list(rev_ids)),
                  ("parent_state", "=", "posted"),
                  ("date", ">=", str(start)), ("date", "<=", str(end))]
        if company_id:
            domain.append(("company_id", "=", company_id))
        rev = op = staff = sub = 0.0
        for ln in self.env["account.move.line"].search_read(
                domain, ["balance", "company_id", "account_id", "partner_id"]):
            cid = ln["company_id"][0] if ln["company_id"] else 0
            aid = ln["account_id"][0]
            pid = ln["partner_id"][0] if ln["partner_id"] else 0
            is_ic = (pid in ic_partners
                     or bool(PEOPLE_IC_ACCOUNT_PAT.match(names.get(aid, ""))))
            if not company_id and is_ic:
                continue
            value = (ln["balance"] or 0.0) * factors.get(cid, 1.0)
            if aid in rev_ids:
                rev -= value
            else:
                op += value
                if aid in staff_ids:
                    staff += value
                elif aid in sub_ids:
                    sub += value
        return {"usd": usd, "factors": factors, "revenue": rev,
                "operating": op, "staff": staff, "sub": sub,
                "people": staff + sub, "other": max(op - staff - sub, 0.0)}

    def _people_usd_short(self, value):
        sign = "−" if value < 0 else ""
        amount = abs(value or 0.0)
        if amount >= 999.5:
            return "%s$%sK" % (sign, "{:,.0f}".format(round(amount / 1000.0)))
        return "%s$%s" % (sign, "{:,.0f}".format(round(amount)))

    def _people_cost_widgets(self, data, company_id, start, end, headcount,
                             scope_note):
        """The Cost & compensation section — group ratios from the ledger
        (work today, all companies) + per-person detail from Odoo wages
        (whatever is loaded; India first, others as their pay goes in)."""
        widgets = [self._people_sechead("people_sec_cost",
                                        _("Cost & compensation"))]
        ledger = self._people_cost_ledger(company_id, start, end)
        if not ledger:
            return widgets
        factors = ledger["factors"]
        usd = ledger["usd"]

        # --- salary % of overhead (donut) ---
        op = ledger["operating"]
        people_pct = round(ledger["people"] / op * 100) if op else 0
        donut = {
            "id": "people_cost_share", "name": _("People as a Share of Operating Cost"),
            "type": "donut", "model": "account.move.line", "mode": "computed",
            "measure": _("of operating cost is people"), "groupby": _("Cost"),
            "color": TEAL,
            "help": _("Of every unit spent running the business, how much is "
                      "people. From the accounting ledger, %(basis)s. Staff = "
                      "own payroll accounts; subcontractors = outsourced "
                      "delivery ('Partners'). Classification is tunable.") % {
                "basis": _("group, intercompany removed") if not company_id
                else scope_note},
            "value": float(people_pct), "format": "percent", "domain": [],
            "points": [
                {"label": _("Staff salaries"),
                 "value": round(ledger["staff"]), "domain": []},
                {"label": _("Subcontractors / partners"),
                 "value": round(ledger["sub"]), "domain": []},
                {"label": _("Everything else"),
                 "value": round(ledger["other"]), "domain": []},
            ],
        }

        # --- people cost vs revenue + revenue per head ---
        rev = ledger["revenue"]
        cost_rev_pct = round(ledger["people"] / rev * 100) if rev > 0 else 0
        rev_per_head = (rev / headcount) if headcount else 0.0
        cost_vs_rev = self._people_kpi(
            "people_cost_revenue", _("People Cost vs Revenue"),
            cost_rev_pct, "percent",
            _("%(p)s people cost · %(r)s revenue") % {
                "p": self._people_usd_short(ledger["people"]),
                "r": self._people_usd_short(rev)}, TEAL,
            _("People cost as a share of revenue over the period — are we "
              "the right size for the money we support? Ledger, USD.") + " "
            + scope_note,
            hero=False, span=4,
            value_text=_("≈ %s%%") % cost_rev_pct)
        rev_head = self._people_kpi(
            "people_rev_head", _("Revenue per Head"), round(rev_per_head),
            "usd", _("revenue ÷ %s people (period)") % headcount, TEAL,
            _("What the average person's revenue contribution is. Ledger "
              "revenue ÷ headcount.") + " " + scope_note,
            span=4, value_text=self._people_usd_short(rev_per_head))

        widgets += [donut, cost_vs_rev, rev_head]

        # --- per-person wage detail (whatever is loaded) ---
        priced = [p for p in data["people"] if (p.get("wage") or 0) > 0]
        payroll_month = sum((p["wage"] or 0) * factors.get(p["company_id"], 1.0)
                            for p in priced)
        if not priced:
            widgets.append(self._people_kpi(
                "people_payroll_empty", _("Team Payroll"), 0, "integer",
                _("no wages entered in Odoo yet"), AMBER,
                _("Once employee wages are entered in Odoo, this lights up "
                  "with total payroll, cost per team and salary bands — "
                  "group-wide in USD, whichever countries have pay loaded."),
                span=4))
            return widgets

        payroll_year = payroll_month * PEOPLE_MONTHS
        widgets.append(self._people_kpi(
            "people_payroll", _("Team Payroll (loaded)"),
            round(payroll_year), "usd",
            _("%(n)s of %(t)s people priced · %(m)s/mo") % {
                "n": len(priced), "t": headcount,
                "m": self._people_usd_short(payroll_month)}, TEAL,
            _("Annualised payroll from wages entered in Odoo, USD at today's "
              "rates. Shows whoever has pay loaded (India first; SA & "
              "Indonesia join as theirs go in).") + " " + scope_note,
            span=4, value_text=self._people_usd_short(payroll_year)))

        # cost per department (USD/yr)
        dept_cost = {}
        for p in priced:
            key = p["dept"] or _("No department")
            entry = dept_cost.setdefault(key, {"usd": 0.0, "ids": []})
            entry["usd"] += (p["wage"] or 0) * factors.get(p["company_id"], 1.0) \
                * PEOPLE_MONTHS
            entry["ids"] += p["emp_ids"]
        dept_points = [{
            "label": name, "value": round(entry["usd"]), "color": TEAL,
            "domain": self._json_safe([("id", "in", entry["ids"])]),
        } for name, entry in sorted(dept_cost.items(), key=lambda kv: -kv[1]["usd"])]
        widgets.append(self._people_bar(
            "people_cost_dept", _("Cost by Department (USD/yr)"), dept_points,
            _("Annual payroll by team, from loaded wages, USD.") + " "
            + scope_note, _("Cost"), _("Department")))

        # salary bands (monthly USD)
        band_defs = [("< $500", 0, 500), ("$500–1.5k", 500, 1500),
                     ("$1.5–3k", 1500, 3000), ("$3k+", 3000, 10 ** 9)]
        shades = ["#6bb3ba", "#3a97a0", "#1a7f89", "#0f6b74"]
        band_points = []
        for i, (label, lo, hi) in enumerate(band_defs):
            n = sum(1 for p in priced
                    if lo <= (p["wage"] or 0) * factors.get(p["company_id"], 1.0) < hi)
            band_points.append({"label": label, "value": n,
                                "color": shades[i], "domain": [], "detail": None})
        widgets.append({
            "id": "people_bands", "name": _("Salary Bands (USD/mo)"),
            "type": "column", "model": "", "mode": "computed",
            "measure": _("People"), "groupby": _("Band"), "color": TEAL,
            "help": _("Monthly gross spread, USD — a common yardstick across "
                      "countries.") + " " + scope_note,
            "value": float(len(priced)), "format": "integer", "domain": [],
            "points": band_points, "rows": [], "columns": [], "span": 6,
            "error": False, "target": 0.0, "tall": True})
        return widgets

    def _people_matrix(self, wid, name, rows, columns, help_text, groupby,
                       span=12):
        widget = self._sales_matrix(wid, name, rows, columns, help_text,
                                    groupby, span=span, compact=True,
                                    color=TEAL)
        # Model left blank: each row carries its own model/domain, and rows
        # without one are inert (openRecords no-ops on an empty model).
        widget["model"] = ""
        return widget
