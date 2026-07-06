import re
from datetime import timedelta

from odoo import fields, models, _

PEOPLE_DASHBOARD_NAME = "Aurika People Dashboard"

# Leftover payroll test/dummy employee records that must never count as people.
PEOPLE_TEST_PAT = re.compile(r"zz_uat|dummy|^test\b|\btest\b", re.IGNORECASE)

# Studio / standard hr.employee fields (skip gracefully if absent).
PEOPLE_JOIN_FIELD = "x_studio_date_of_joining"
PEOPLE_SEX_FIELD = "sex"

# Cost section — classify operating-expense accounts into "people cost" by
# NAME (tunable, like the Finance dashboard's EBITDA account rules). Staff =
# own payroll; subcontractors = outsourced delivery ("Partners" here).
PEOPLE_STAFF_PAT = re.compile(
    r"salar|payroll|\bpaye\b|\bfte\b|\bwage|staff|personnel|\bctc\b", re.I)
PEOPLE_SUB_PAT = re.compile(
    r"partner|subcontract|contractor|freelanc|associate|outsourc", re.I)
PEOPLE_IC_ACCOUNT_PAT = re.compile(r"^ic\b", re.I)
PEOPLE_MONTHS = 12  # annualise a monthly wage

# T&M sale lines (LinkedERP product-code convention, same as the SLA
# dashboard): billable hours on these lines are valued at the line's own
# customer rate; everything else at the window's blended realized rate.
PEOPLE_TM_PRODUCT = re.compile(r"^[A-Z]{2}SPT", re.IGNORECASE)

PEOPLE_SERIES_MONTHS = 13   # charts: 12 full months + the current one
PEOPLE_BONUS_SHARE = 60.0   # payroll-share months above this get amber

PEOPLE_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

TEAL = "#0f6b74"
GREEN = "#0f7a52"
RED = "#c0392f"
AMBER = "#b45309"
GOLD = "#b8860b"


class LinkederpDashboardPeople(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_people_dashboard()

    def _ensure_people_dashboard(self):
        description = _(
            "The MDs' people cockpit: who we are, what we cost, and whether "
            "the cost earns its keep — headcount and true attrition "
            "(duplicate leaver cards quarantined), payroll vs overheads and "
            "revenue, salary coverage, all companies in USD.")
        if self._ensure_dashboard_name(PEOPLE_DASHBOARD_NAME, []):
            # One-time copy refresh (v4 dropped "separate phase" wording).
            record = self.with_context(active_test=False).search(
                [("name", "=", PEOPLE_DASHBOARD_NAME)], limit=1)
            if record and "separate phase" in (record.description or ""):
                record.write({"description": description})
            return
        if "hr.employee" not in self.env:
            return
        self.create({
            "name": PEOPLE_DASHBOARD_NAME,
            "sequence": 80,
            "bucket": "management",
            "description": description,
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

    @staticmethod
    def _people_match_norm(name):
        """Aggressive form used ONLY for matching duplicate cards: cut at
        ' - ' (e.g. '(ZA) - Resigned', '- Linked ERP (Pty) Ltd'), strip a
        trailing '(XX)'/'(XXX)' company tag even glued to the name."""
        base = (name or "").split(" - ")[0]
        base = re.sub(r"\s*\([A-Za-z]{2,3}\)\s*$", "", base)
        return re.sub(r"\s+", " ", base).strip().lower()

    @classmethod
    def _people_name_keys(cls, name):
        """Match keys for one name: exact norm + (first,last) + (first,2nd)
        token pairs — catches middle initials ('Prathuk B Hedge') and
        trailing initials ('Vaishak Gowda Ys')."""
        nm = cls._people_match_norm(name)
        keys = {("x", nm)} if nm else set()
        tokens = nm.split()
        if len(tokens) >= 2:
            keys.add(("fl", tokens[0], tokens[-1]))
            keys.add(("f2", tokens[0], tokens[1]))
        return keys

    def _people_is_test(self, name):
        return bool(PEOPLE_TEST_PAT.search(name or ""))

    def _people_collect(self, company_id):
        """Person-deduped active population + TRUE leavers + quarantined
        phantom leaver cards + leaves. `company_id` = 0 means the group."""
        today = fields.Date.context_today(self)
        Employee = self.env["hr.employee"]
        efields = Employee._fields
        has_join = PEOPLE_JOIN_FIELD in efields
        has_sex = PEOPLE_SEX_FIELD in efields
        has_wage = "wage" in efields
        has_birthday = "birthday" in efields
        companies = self.env["res.company"].search([])
        company_names = {c.id: c.name for c in companies}

        read_fields = ["name", "user_id", "company_id", "department_id",
                       "parent_id"]
        if has_join:
            read_fields.append(PEOPLE_JOIN_FIELD)
        if has_sex:
            read_fields.append(PEOPLE_SEX_FIELD)
        if has_wage:
            read_fields.append("wage")
        if has_birthday:
            read_fields.append("birthday")

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
                    "birthday": e.get("birthday") if has_birthday else False,
                    "has_mgr": bool(e.get("parent_id")),
                    # Monthly wage in the record's company currency; 0 until
                    # entered. Converted to USD per home company in the cost
                    # section (never hardcoded to one currency/country).
                    "wage": e.get("wage") if has_wage else 0.0,
                    "_home": is_home,
                }
            else:
                persons[pid]["emp_ids"].append(e["id"])
                if not persons[pid]["has_mgr"] and e.get("parent_id"):
                    persons[pid]["has_mgr"] = True

        # match indexes of the ACTIVE population (for phantom detection)
        active_uids = set(user_ids)
        active_keys = set()
        for e in real:
            active_keys |= self._people_name_keys(e["name"])

        # scope to a single company (home company) if asked
        people = list(persons.values())
        if company_id:
            people = [p for p in people if p["company_id"] == company_id]

        no_login = sum(1 for p in people if p["pid"][0] == "n")
        no_dept = sum(1 for p in people if not p["dept_id"])
        no_mgr = sum(1 for p in people if not p["has_mgr"])
        test_scoped = [e for e in test_records
                       if not company_id
                       or (e["company_id"] and e["company_id"][0] == company_id)]

        # ---- departed cards → ONE row per person, phantom vs TRUE ----
        dep_fields = ["name", "user_id", "company_id", "department_id",
                      "departure_date", "departure_reason_id"]
        if has_join:
            dep_fields.append(PEOPLE_JOIN_FIELD)
        dep_person = {}
        fuzzy_only = set()
        for e in Employee.with_context(active_test=False).search_read(
                [("departure_date", "!=", False)], dep_fields):
            if self._people_is_test(e["name"]):
                continue
            cid = e["company_id"][0] if e["company_id"] else 0
            uid_val = e["user_id"][0] if e["user_id"] else None
            person_company = (home.get(uid_val)
                              if uid_val and home.get(uid_val) else cid)
            keys = self._people_name_keys(e["name"])
            fl = next((k for k in keys if k[0] == "fl"), None)
            pkey = fl or next(iter(keys), ("x", self._people_norm(e["name"])))
            d = str(e["departure_date"])[:10]
            exact_hit = ("x", self._people_match_norm(e["name"])) in active_keys
            user_hit = bool(uid_val and uid_val in active_uids)
            is_phantom = bool(user_hit or (keys & active_keys))
            if is_phantom and not exact_hit and not user_hit:
                fuzzy_only.add(pkey)
            cur = dep_person.get(pkey)
            if cur is None or d > cur["date"]:
                dep_person[pkey] = {
                    "key": pkey,
                    "emp_id": e["id"],
                    "name": self._people_match_norm(e["name"]).title(),
                    "date": d,
                    "dept": (e["department_id"][1]
                             if e["department_id"] else False),
                    "company_id": person_company,
                    "join": ((e.get(PEOPLE_JOIN_FIELD) if has_join else False)
                             or (cur["join"] if cur else False)),
                    "reason": (e["departure_reason_id"][1]
                               if e["departure_reason_id"]
                               else _("Not recorded")),
                    "phantom": is_phantom,
                }
            else:
                if not cur["join"] and has_join and e.get(PEOPLE_JOIN_FIELD):
                    cur["join"] = e[PEOPLE_JOIN_FIELD]
                cur["phantom"] = cur["phantom"] or is_phantom

        departed, phantoms = [], []
        for row in dep_person.values():
            if company_id and row["company_id"] != company_id:
                continue
            (phantoms if row["phantom"] else departed).append(row)
        departed.sort(key=lambda r: r["date"])
        phantoms.sort(key=lambda r: r["date"])

        # validated leave (widest window = 13 months back)
        leaves = []
        leave_by_person = {}
        emp_person = {}
        for p in people:
            for eid in p["emp_ids"]:
                emp_person[eid] = p
        if "hr.leave" in self.env:
            floor = str(today - timedelta(days=400))
            lv_domain = [("state", "=", "validate"),
                         ("date_from", ">=", floor)]
            if company_id:
                lv_domain.append(("employee_id.company_id", "=", company_id))
            for l in self.env["hr.leave"].search_read(
                    lv_domain, ["number_of_days", "holiday_status_id",
                                "date_from", "employee_id"]):
                leaves.append({
                    "id": l["id"],
                    "days": l["number_of_days"] or 0.0,
                    "type": (l["holiday_status_id"][1]
                             if l["holiday_status_id"] else _("Other")),
                    "type_id": (l["holiday_status_id"][0]
                                if l["holiday_status_id"] else False),
                    "date": str(l["date_from"])[:10],
                })
                emp = l["employee_id"][0] if l["employee_id"] else 0
                person = emp_person.get(emp)
                if person:
                    leave_by_person[person["pid"]] = \
                        leave_by_person.get(person["pid"], 0.0) \
                        + (l["number_of_days"] or 0.0)

        return {
            "today": today,
            "companies": [(c.id, c.name) for c in companies],
            "company_names": company_names,
            "people": people,
            "departed": departed,      # TRUE leavers only
            "phantoms": phantoms,      # quarantined duplicate cards
            "fuzzy_variants": len(fuzzy_only),
            "leaves": leaves,
            "leave_by_person": leave_by_person,
            "has_join": has_join,
            "has_sex": has_sex,
            "hygiene": {"test": len(test_scoped),
                        "test_ids": [e["id"] for e in test_scoped],
                        "no_login": no_login, "no_dept": no_dept,
                        "no_mgr": no_mgr},
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
    # Month helpers + headcount series
    # ------------------------------------------------------------------
    @staticmethod
    def _people_month_keys(today, count=PEOPLE_SERIES_MONTHS):
        keys = []
        y, m = today.year, today.month
        for _i in range(count):
            keys.append((y, m))
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        return list(reversed(keys))

    @staticmethod
    def _people_month_label(key):
        return "%s '%02d" % (PEOPLE_MONTH_LABELS[key[1] - 1], key[0] % 100)

    @staticmethod
    def _people_month_end(key, today):
        first = fields.Date.to_date("%04d-%02d-01" % key)
        me = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return min(me, today)

    def _people_monthly_series(self, people, departed, today):
        """[{key,label,end,hc,joined,left,join_ids,left_ids}] over the last
        13 months. hc = actives whose join ≤ month-end (people without a
        join date always count) + true leavers still employed then."""
        series = []
        for key in self._people_month_keys(today):
            me = self._people_month_end(key, today)
            ms = me.replace(day=1)
            hc = 0
            join_ids = []
            for p in people:
                j = self._people_safe_date(p["join"])
                if j is None or j <= me:
                    hc += 1
                if j and ms <= j <= me:
                    join_ids.append(p["emp_ids"][0])
            left_ids = []
            for dep in departed:
                x = self._people_safe_date(dep["date"])
                j = self._people_safe_date(dep["join"])
                if x and x > me and (j is None or j <= me):
                    hc += 1
                if x and ms <= x <= me:
                    left_ids.append(dep["emp_id"])
                if j and ms <= j <= me and x and x > me:
                    join_ids.append(dep["emp_id"])
            series.append({
                "key": key, "label": self._people_month_label(key),
                "end": me, "hc": hc,
                "joined": len(join_ids), "left": len(left_ids),
                "join_ids": join_ids, "left_ids": left_ids,
            })
        return series

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
                    model="hr.employee", span=6, fmt="integer"):
        return {"id": wid, "name": name, "type": "bar", "model": model,
                "mode": "computed", "measure": measure, "groupby": groupby,
                "color": TEAL, "help": help_text, "value": float(len(points)),
                "format": fmt, "domain": [], "points": points,
                "rows": [], "columns": [], "span": span, "error": False}

    def _people_column(self, wid, name, points, help_text, measure, groupby,
                       model="", span=6, fmt="integer", color=TEAL):
        return {"id": wid, "name": name, "type": "column", "model": model,
                "mode": "computed", "measure": measure, "groupby": groupby,
                "color": color, "help": help_text,
                "value": float(sum(p.get("value") or 0 for p in points)),
                "format": fmt, "domain": [], "points": points,
                "rows": [], "columns": [], "span": span, "error": False,
                "target": 0.0}

    def _people_roster(self, wid, title, rows_data, metric_label, help_text):
        """A popup listing people — Name · Department · <metric> — where each
        row clicks through to that person's Odoo record. rows_data items:
        {label, domain, dept, metric}."""
        rows = [{
            "label": r["label"],
            "domain": r["domain"],
            "model": "hr.employee",
            "dept": r.get("dept") or "—",
            "metric": r.get("metric", ""),
            "tones": {},
        } for r in rows_data]
        widget = self._sales_matrix(
            wid, title, rows,
            [{"key": "dept", "label": _("Department"), "format": "text"},
             {"key": "metric", "label": metric_label, "format": "text"}],
            help_text, _("Name"), span=12, compact=True, color=TEAL)
        widget["model"] = "hr.employee"
        return widget

    def _people_person_rows(self, subset, metric_fn):
        return [{"label": p["name"],
                 "domain": self._json_safe([("id", "in", p["emp_ids"])]),
                 "dept": p["dept"], "metric": metric_fn(p)}
                for p in subset]

    def _people_leaver_rows(self, subset, metric_fn):
        return [{"label": d["name"],
                 "domain": self._json_safe([("id", "=", d["emp_id"])]),
                 "dept": d["dept"], "metric": metric_fn(d)}
                for d in subset]

    def _people_matrix(self, wid, name, rows, columns, help_text, groupby,
                       span=12):
        widget = self._sales_matrix(wid, name, rows, columns, help_text,
                                    groupby, span=span, compact=True,
                                    color=TEAL)
        # Model left blank: each row carries its own model/domain, and rows
        # without one are inert (openRecords no-ops on an empty model).
        widget["model"] = ""
        return widget

    def _people_month_table(self, wid, title, rows, columns, help_text):
        return self._people_matrix(wid, title, rows, columns, help_text,
                                   _("Month"))

    # ------------------------------------------------------------------
    # Ledger — monthly people cost / operating cost / revenue (USD)
    # ------------------------------------------------------------------
    def _people_cost_ledger(self, company_id, today):
        """Monthly series (last 13 calendar months) + trailing-12 totals of
        people cost, total operating cost and revenue — ledger, USD,
        intercompany stripped on the group view. Reuses the Finance account
        buckets so the two dashboards can never disagree."""
        if "account.move.line" not in self.env:
            return None
        usd = self._mgmt_usd()
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
        keys = self._people_month_keys(today)
        floor = fields.Date.to_date("%04d-%02d-01" % keys[0])
        domain = [("account_id", "in", op_ids + list(rev_ids)),
                  ("parent_state", "=", "posted"),
                  ("date", ">=", str(floor)), ("date", "<=", str(today))]
        if company_id:
            domain.append(("company_id", "=", company_id))
        monthly = {k: {"people": 0.0, "op": 0.0, "rev": 0.0}
                   for k in keys}
        for ln in self.env["account.move.line"].search_read(
                domain, ["balance", "company_id", "account_id",
                         "partner_id", "date"]):
            cid = ln["company_id"][0] if ln["company_id"] else 0
            aid = ln["account_id"][0]
            pid = ln["partner_id"][0] if ln["partner_id"] else 0
            is_ic = (pid in ic_partners
                     or bool(PEOPLE_IC_ACCOUNT_PAT.match(names.get(aid, ""))))
            if not company_id and is_ic:
                continue
            lkey = (ln["date"].year, ln["date"].month)
            slot = monthly.get(lkey)
            if slot is None:
                continue
            value = (ln["balance"] or 0.0) * factors.get(cid, 1.0)
            if aid in rev_ids:
                slot["rev"] -= value
            else:
                slot["op"] += value
                if aid in staff_ids or aid in sub_ids:
                    slot["people"] += value
        series = [{
            "key": k, "label": self._people_month_label(k),
            "people": monthly[k]["people"], "op": monthly[k]["op"],
            "rev": monthly[k]["rev"],
        } for k in keys]
        window = series[:-1]  # the 12 full months before the current one
        totals = {
            "people": sum(m["people"] for m in window),
            "op": sum(m["op"] for m in window),
            "rev": sum(m["rev"] for m in window),
        }
        return {"usd": usd, "factors": factors, "series": series,
                "totals": totals,
                "staff_ids": list(staff_ids), "sub_ids": list(sub_ids),
                "op_ids": op_ids}

    def _people_usd_short(self, value):
        sign = "−" if value < 0 else ""
        amount = abs(value or 0.0)
        if amount >= 999.5:
            return "%s$%sK" % (sign, "{:,.0f}".format(round(amount / 1000.0)))
        return "%s$%s" % (sign, "{:,.0f}".format(round(amount)))

    # ------------------------------------------------------------------
    # Billable value / salary coverage engine (shared with Aurika Ops)
    # ------------------------------------------------------------------
    def _people_billable_data(self, today, ledger):
        """Billable project timesheets of the last 13 months, valued:
        ××SPT sale-line hours at the line's own rate (converted to USD),
        everything else at the window's blended realized rate (ledger
        revenue ÷ total billable hours — self-updating, no constants)."""
        Line = self.env["account.analytic.line"]
        if "timesheet_invoice_type" not in Line._fields or not ledger:
            return None
        keys = self._people_month_keys(today)
        floor = fields.Date.to_date("%04d-%02d-01" % keys[0])
        has_so = "so_line" in Line._fields
        fields_list = ["date", "unit_amount", "user_id"]
        if has_so:
            fields_list.append("so_line")
        raw = Line.search_read(
            [("project_id", "!=", False),
             ("timesheet_invoice_type", "!=", "non_billable"),
             ("date", ">=", str(floor)), ("date", "<=", str(today))],
            fields_list)
        usd = ledger["usd"]
        sol_rate = {}

        def rate_for(sol_id):
            if sol_id not in sol_rate:
                sol = self.env["sale.order.line"].browse(sol_id)
                rate = 0.0
                if sol.exists() and PEOPLE_TM_PRODUCT.match(
                        sol.product_id.name or ""):
                    rate = sol.currency_id._convert(
                        sol.price_unit or 0.0, usd,
                        sol.order_id.company_id or self.env.company,
                        today, round=False)
                sol_rate[sol_id] = rate
            return sol_rate[sol_id]

        total_hours = 0.0
        monthly_user = {}
        for ln in raw:
            hours = ln["unit_amount"] or 0.0
            uid_val = ln["user_id"][0] if ln["user_id"] else 0
            lkey = (ln["date"].year, ln["date"].month)
            total_hours += hours
            rate = (rate_for(ln["so_line"][0])
                    if has_so and ln.get("so_line") else 0.0)
            slot = monthly_user.setdefault(lkey, {}).setdefault(
                uid_val, {"hours": 0.0, "value": 0.0, "fallback_h": 0.0,
                          "line_ids": []})
            slot["hours"] += hours
            slot["line_ids"].append(ln["id"])
            if rate:
                slot["value"] += hours * rate
            else:
                slot["fallback_h"] += hours
        blended = (ledger["totals"]["rev"] / total_hours) \
            if total_hours else 0.0
        for per_user in monthly_user.values():
            for slot in per_user.values():
                if slot["fallback_h"]:
                    slot["value"] += slot["fallback_h"] * blended
        return {"monthly_user": monthly_user, "blended": blended,
                "keys": keys}

    def _people_coverage_rows(self, data, billable, today):
        """Per-person salary coverage for the latest month WITH billable
        delivery data (walks back ≤ 4 months): ops-tagged users with a
        wage. Coverage % = billable value ÷ monthly salary × 100."""
        if not billable:
            return None
        primary = self._ops_primary_employees()
        person_by_uid = {}
        for p in data["people"]:
            if p["pid"][0] == "u":
                person_by_uid[p["pid"][1]] = p
        factors = data.get("_factors") or {}

        def ops_hours(key):
            per_user = billable["monthly_user"].get(key) or {}
            return sum(slot["hours"] for uid_val, slot in per_user.items()
                       if uid_val in primary)

        # Latest month with a REAL delivery volume (≥ 100 ops hours — a
        # few stray entries in an otherwise empty month must not become
        # "the" coverage month); else the fullest month of the window.
        month_key = None
        for key in list(reversed(billable["keys"]))[:4]:
            if ops_hours(key) >= 100.0:
                month_key = key
                break
        if month_key is None:
            month_key = max(billable["keys"], key=ops_hours)
            if ops_hours(month_key) <= 0:
                return None
        rows = []
        per_user = billable["monthly_user"].get(month_key, {})
        for uid_val in primary:
            person = person_by_uid.get(uid_val)
            if not person or (person.get("wage") or 0.0) <= 0:
                continue
            slot = per_user.get(uid_val, {"hours": 0.0, "value": 0.0,
                                          "line_ids": []})
            salary = (person["wage"] or 0.0) * factors.get(
                person["company_id"], 1.0)
            cov = (slot["value"] / salary * 100.0) if salary else 0.0
            rows.append({
                "person": person,
                "name": person["name"],
                "hours": slot["hours"],
                "value": slot["value"],
                "salary": salary,
                "cov": cov,
                "line_ids": slot.get("line_ids", []),
            })
        rows.sort(key=lambda r: -r["cov"])
        return {"key": month_key,
                "label": self._people_month_label(month_key),
                "rows": rows}

    def _people_salary_coverage_widget(self):
        """💰 Salary Coverage for the AURIKA OPS dashboard (Akshay-approved):
        one column per priced delivery person — billable value ÷ salary for
        the latest month with data. 100% = earns their own salary."""
        if "hr.employee" not in self.env or \
                "account.move.line" not in self.env:
            return None
        today = fields.Date.context_today(self)
        data = self._people_collect(0)
        ledger = self._people_cost_ledger(0, today)
        if not ledger:
            return None
        data["_factors"] = ledger["factors"]
        billable = self._people_billable_data(today, ledger)
        coverage = self._people_coverage_rows(data, billable, today)
        if not coverage or not coverage["rows"]:
            return None
        points = []
        for row in coverage["rows"]:
            tone = (GREEN if row["cov"] >= 200 else
                    "#d08a2e" if row["cov"] >= 100 else RED)
            points.append({
                "label": row["name"].split()[0],
                "value": round(row["cov"]),
                "color": tone,
                "domain": self._json_safe([("id", "in", row["line_ids"])]),
                "detail": None,
                "modal_table": self._people_matrix(
                    "mgmt_cov_%s" % row["person"]["emp_ids"][0],
                    _("%s — %s") % (row["name"], coverage["label"]),
                    [
                        {"label": _("Billable hours"),
                         "domain": self._json_safe(
                             [("id", "in", row["line_ids"])]),
                         "model": "account.analytic.line",
                         "val": "%.0f h" % row["hours"], "tones": {}},
                        {"label": _("Billable value (SO rate / blended)"),
                         "domain": [],
                         "val": self._people_usd_short(row["value"]),
                         "tones": {}},
                        {"label": _("Monthly salary (USD)"), "domain": [],
                         "val": self._people_usd_short(row["salary"]),
                         "tones": {}},
                        {"label": _("Coverage"), "domain": [],
                         "val": "%d%%" % round(row["cov"]),
                         "tones": {"val": "good" if row["cov"] >= 200
                                   else "warn" if row["cov"] >= 100
                                   else "bad"}},
                    ],
                    [{"key": "val", "label": _("Value"), "format": "money"}],
                    _("Click the hours row for the person's time entries."),
                    _("Step")),
            })
        widget = self._people_column(
            "mgmt_salary_coverage",
            _("💰 Salary Coverage — %s") % coverage["label"],
            points,
            _("Billable value ÷ salary per delivery person, latest month "
              "with data. 100%% = the person earns their own salary (dotted "
              "line). Green ≥ 200%%, amber 100–200%%, red below. Hours are "
              "valued at the T&M sale-line rate, else at the trailing "
              "blended rate. Only people with wages loaded appear."),
            _("Coverage"), _("Person"), model="account.analytic.line",
            span=12, fmt="percent", color="#1e5b96")
        widget["target"] = 100.0
        return widget

    # ------------------------------------------------------------------
    # The dashboard (v4)
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
        departed = data["departed"]
        phantoms = data["phantoms"]
        headcount = len(people)

        company_name = ""
        if company_id:
            company_name = dict(data["companies"]).get(company_id, "")
        scope_note = (_("%s only.") % company_name if company_id
                      else _("All companies, counted by person."))

        series = self._people_monthly_series(people, departed, today)
        hc_prior = series[0]["hc"]

        # ---- movement (TRUE leavers only) ----
        exits = self._people_exits(departed, start, end)
        raw_exits = exits + self._people_exits(phantoms, start, end)
        avg_hc = (series[-1]["hc"] + series[0]["hc"]) / 2.0 or 1.0
        attrition = round(len(exits) / avg_hc * 100)
        raw_attrition = round(len(raw_exits) / avg_hc * 100)
        last_exit = max((d["date"] for d in departed), default="")

        # ---- gender ----
        sex_counts = {}
        for p in people:
            sex_counts[p["sex"] or "unset"] = sex_counts.get(
                p["sex"] or "unset", 0) + 1
        male = sex_counts.get("male", 0)
        female = sex_counts.get("female", 0)
        unset = sex_counts.get("unset", 0)

        # ---- company split ----
        comp_split = []
        for cid, cname in data["companies"]:
            n = sum(1 for p in people if p["company_id"] == cid)
            if n:
                comp_split.append((cname, n))
        comp_split.sort(key=lambda x: -x[1])
        comp_caption = " · ".join("%s %s" % (n.split()[0], c)
                                  for n, c in comp_split) or _("—")

        # ---- tenure & age ----
        tenures = [self._people_years(p["join"], today) for p in people]
        median_tenure = self._people_median(tenures)
        ages = []
        bad_birthday = 0
        for p in people:
            b = self._people_safe_date(p.get("birthday"))
            if not b:
                continue
            age = (today - b).days / 365.25
            if age > 80 or age < 15:
                bad_birthday += 1
            else:
                ages.append(age)
        median_age = self._people_median(ages)
        no_birthday = sum(1 for p in people
                          if not self._people_safe_date(p.get("birthday")))

        # ---- money engines ----
        ledger = self._people_cost_ledger(company_id, today)
        billable = (self._people_billable_data(today, ledger)
                    if ledger else None)
        if ledger:
            data["_factors"] = ledger["factors"]
        coverage = (self._people_coverage_rows(data, billable, today)
                    if billable else None)

        active_emp_ids = [eid for p in people for eid in p["emp_ids"]]

        def _yrs(p):
            y = self._people_years(p["join"], today)
            return (_("%s yrs") % round(y, 1) if y is not None
                    else _("— (no date)"))
        _sex_label = {"male": _("Man"), "female": _("Woman")}

        def _sexlbl(p):
            return _sex_label.get(p["sex"], _("Not recorded"))

        def leaver_when(d):
            return self._ops_date_text(self._people_safe_date(d["date"]))

        # ---- header chips ----
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
                 "text": _("Window: %s") % period_label},
                {"icon": "fa-user", "tone": "",
                 "text": _("Counted by person, duplicate cards quarantined")},
                {"icon": "fa-hand-o-up", "tone": "",
                 "text": _("Every card opens a pop-up")},
            ],
        }

        # ---- popups reused by the hero row ----
        gender_popup = self._people_roster(
            "people_gender_list", _("Team by Gender"),
            self._people_person_rows(
                sorted(people, key=lambda p: (p["sex"] or "z", p["name"])),
                _sexlbl),
            _("Gender"),
            _("Everyone, with their recorded gender.") + " " + scope_note)
        tenure_popup = self._people_roster(
            "people_tenure_list", _("Tenure per Person"),
            self._people_person_rows(
                sorted(people, key=lambda p: -(
                    self._people_years(p["join"], today) or 0)),
                _yrs),
            _("Tenure"),
            _("Everyone, longest-serving first.") + " " + scope_note)
        roster_popup = self._people_roster(
            "people_roster", _("The %s people") % headcount,
            self._people_person_rows(
                sorted(people, key=lambda p: p["name"]), _yrs),
            _("Tenure"),
            _("Everyone counted. Click a name for the record.") + " "
            + scope_note)
        phantom_popup = self._people_roster(
            "people_phantom_list",
            _("%s phantom leaver cards — still working here") % len(phantoms),
            self._people_leaver_rows(
                phantoms, lambda d: _("card says left %s") % leaver_when(d)),
            _("Card says"),
            _("Duplicate employee cards archived with a departure date "
              "while the person is still on the active roster. Clearing "
              "these dates fixes attrition at the source."))

        rev12 = ledger["totals"]["rev"] if ledger else 0.0
        rev_head = (rev12 / headcount) if headcount else 0.0

        hero = [
            self._people_kpi(
                "people_headcount", _("Headcount"), headcount, "integer",
                _("people · %s") % comp_caption, TEAL,
                _("Distinct people (by Odoo user), duplicate and test cards "
                  "excluded. The sparkline is the 13-month curve. Click for "
                  "the roster.") + " " + scope_note,
                model="hr.employee",
                domain=[("id", "in", active_emp_ids)],
                hero="teal", modal_table=roster_popup,
                points=[{"label": m["label"], "value": m["hc"]}
                        for m in series],
                delta=self._people_delta(headcount, hc_prior)),
            self._people_kpi(
                "people_attrition", _("True Attrition · %s") % period_label,
                attrition, "percent",
                _("%(n)s real leavers · raw records claim %(raw)s%%") % {
                    "n": len(exits), "raw": raw_attrition},
                RED if attrition >= 30 else AMBER if attrition >= 15
                else GREEN,
                _("Leavers ÷ average headcount — counting PEOPLE who "
                  "actually left. %(ph)s duplicate 'leaver' cards belong to "
                  "people still on the roster and are quarantined; click to "
                  "see them. Last real exit: %(last)s.") % {
                    "ph": len(phantoms), "last": last_exit or _("—")},
                hero="teal", span=3, value_text="≈ %s%%" % attrition,
                modal_table=phantom_popup),
            self._people_kpi(
                "people_rev_head", _("Revenue per Head"), round(rev_head),
                "usd", _("per person per year · trailing 12"), TEAL,
                _("Ledger revenue of the last 12 full months ÷ headcount. "
                  "Click for the people counted.") + " " + scope_note,
                hero="teal", span=2, modal_table=roster_popup,
                value_text=self._people_usd_short(rev_head)),
            self._people_kpi(
                "people_gender", _("Gender Balance"), male, "integer",
                _("men / women · %s unrecorded") % unset, "#2a92b8",
                _("From the employee gender field. Click for the list.")
                + " " + scope_note,
                hero="teal", span=2, modal_table=gender_popup,
                value_text="%s / %s" % (male, female),
                split=[
                    {"pct": round(male / headcount * 100) if headcount else 0,
                     "color": "#7fc4cb", "label": _("Men")},
                    {"pct": (round(female / headcount * 100)
                             if headcount else 0),
                     "color": "#e0a13a", "label": _("Women")},
                    {"pct": round(unset / headcount * 100) if headcount else 0,
                     "color": "#5b7c85", "label": _("Unset")},
                ]),
            self._people_kpi(
                "people_tenure", _("Median Tenure"), round(median_tenure, 1),
                "number",
                _("median age %s") % (round(median_age) if ages else "—"),
                TEAL,
                _("Years since joining, middle value. Click for tenure per "
                  "person.") + " " + scope_note,
                hero="teal", span=2, modal_table=tenure_popup,
                value_text=_("%s yrs") % round(median_tenure, 1)),
        ]

        # ---- growth: headcount by month + data confidence ----
        hc_rows = []
        for m in series:
            hc_rows.append({
                "label": m["label"],
                "domain": self._json_safe([("id", "in", m["join_ids"])]),
                "model": "hr.employee" if m["join_ids"] else "",
                "hc": str(m["hc"]),
                "joined": "+%s" % m["joined"] if m["joined"] else "0",
                "left": "−%s" % m["left"] if m["left"] else "0",
                "tones": {"left": "bad" if m["left"] else "",
                          "joined": "good" if m["joined"] else ""},
            })
        hc_popup = self._people_month_table(
            "people_hc_table", _("Headcount, month by month"), hc_rows,
            [{"key": "hc", "label": _("People"), "format": "number"},
             {"key": "joined", "label": _("Joined"), "format": "number"},
             {"key": "left", "label": _("Left"), "format": "number"}],
            _("Month-end headcount with joiners and real leavers. A month's "
              "row opens its joiners."))
        hc_points = [{
            "label": m["label"], "value": m["hc"], "color": TEAL,
            "domain": [], "detail": None,
        } for m in series]
        hc_chart = self._people_column(
            "people_hc_monthly", _("Headcount, month by month"), hc_points,
            _("Distinct people at each month-end, duplicate cards removed. "
              "History is reconstructed from joining and exit dates. Click "
              "for the table.") + " " + scope_note,
            _("People"), _("Month"), span=8)
        hc_chart["modal_table"] = hc_popup

        wageless = sum(1 for p in people if (p.get("wage") or 0) <= 0)
        hyg = data["hygiene"]
        confidence_rows = [
            {"label": _("Leaver cards for people still working here"),
             "domain": [], "model": "",
             "val": "%s" % len(phantoms),
             "status": _("clear the dates") if phantoms else _("clean"),
             "tones": {"status": "bad" if phantoms else "good"},
             "modal_table": phantom_popup if phantoms else False},
            {"label": _("Duplicate cards caught only by fuzzy name match"),
             "domain": [], "val": "%s" % data["fuzzy_variants"],
             "status": (_("merge / rename") if data["fuzzy_variants"]
                        else _("clean")),
             "tones": {"status": "warn" if data["fuzzy_variants"]
                       else "good"}},
            {"label": _("Test / dummy records still active"),
             "model": "hr.employee" if hyg["test"] else "",
             "domain": self._json_safe([("id", "in", hyg["test_ids"])]),
             "val": "%s" % hyg["test"],
             "status": _("archive") if hyg["test"] else _("clean"),
             "tones": {"status": "warn" if hyg["test"] else "good"}},
            {"label": _("People without a wage in Odoo"),
             "domain": [], "val": _("%(n)s of %(t)s") % {
                 "n": wageless, "t": headcount},
             "status": _("load pay") if wageless else _("complete"),
             "tones": {"status": "warn" if wageless else "good"}},
            {"label": _("Gender / birthday / department missing"),
             "domain": [], "val": "%s · %s · %s" % (
                 unset, no_birthday, hyg["no_dept"]),
             "status": _("fill in"),
             "tones": {"status": "warn" if (unset or no_birthday)
                       else "good"}},
            {"label": _("No manager set · impossible birthdays"),
             "domain": [], "val": "%s · %s" % (hyg["no_mgr"], bad_birthday),
             "status": (_("fix") if (hyg["no_mgr"] or bad_birthday)
                        else _("clean")),
             "tones": {"status": "warn" if (hyg["no_mgr"] or bad_birthday)
                       else "good"}},
        ]
        confidence = self._people_matrix(
            "people_confidence", _("Data Confidence"), confidence_rows,
            [{"key": "val", "label": _("Today"), "format": "money"},
             {"key": "status", "label": _("Status"), "format": "text"}],
            _("What the numbers rest on — every fix makes the page above "
              "more true.") + " " + scope_note,
            _("Check"), span=4)

        # ---- money lens ----
        money = [self._people_sechead("people_sec_money",
                                      _("The money lens on people"))]
        if ledger:
            t = ledger["totals"]
            share12 = round(t["people"] / t["op"] * 100) if t["op"] else 0
            share_rows = []
            for m in ledger["series"]:
                share = (round(m["people"] / m["op"] * 100)
                         if m["op"] > 0 else 0)
                share_rows.append({
                    "label": m["label"], "domain": [],
                    "payroll": self._people_usd_short(m["people"]),
                    "overhead": self._people_usd_short(m["op"]),
                    "share": "%s%%" % share,
                    "tones": {"share": "warn" if share > PEOPLE_BONUS_SHARE
                              else ""},
                })
            share_rows.append({
                "label": _("Trailing 12 months"), "domain": [],
                "payroll": self._people_usd_short(t["people"]),
                "overhead": self._people_usd_short(t["op"]),
                "share": "%s%%" % share12, "tones": {}})
            share_popup = self._people_month_table(
                "people_share_table", _("Payroll vs total overhead"),
                share_rows,
                [{"key": "payroll", "label": _("Payroll cost"),
                  "format": "money"},
                 {"key": "overhead", "label": _("Total overhead"),
                  "format": "money"},
                 {"key": "share", "label": _("Share"), "format": "money"}],
                _("People cost (staff + subcontractors) against everything "
                  "the business spends, per month."))
            share_points = [{
                "label": m["label"],
                "value": (round(m["people"] / m["op"] * 100)
                          if m["op"] > 0 else 0),
                "color": AMBER if (m["op"] > 0 and m["people"] / m["op"] * 100
                                   > PEOPLE_BONUS_SHARE) else TEAL,
                "domain": [], "detail": None,
            } for m in ledger["series"]]
            share_chart = self._people_column(
                "people_payroll_share", _("Payroll as % of Overhead Cost"),
                share_points,
                _("People cost ÷ total operating cost per month, ledger USD"
                  "%(ic)s. Trailing-12: %(s)s%%. Amber months are the bonus/"
                  "batch bookings. Click for the month-by-month table.") % {
                    "ic": "" if company_id else _(", intercompany out"),
                    "s": share12},
                _("Share"), _("Month"), span=6, fmt="percent")
            share_chart["modal_table"] = share_popup

            ratio12 = round(t["people"] / t["rev"] * 100) if t["rev"] else 0
            pcr_rows = []
            for m in ledger["series"]:
                ratio = (round(m["people"] / m["rev"] * 100)
                         if m["rev"] > 0 else 0)
                pcr_rows.append({
                    "label": m["label"], "domain": [],
                    "people": self._people_usd_short(m["people"]),
                    "rev": self._people_usd_short(m["rev"]),
                    "ratio": "%s%%" % ratio if m["rev"] > 0 else "—",
                    "tones": {"ratio": "bad" if ratio > 100 else ""},
                })
            pcr_rows.append({
                "label": _("Trailing 12 months"), "domain": [],
                "people": self._people_usd_short(t["people"]),
                "rev": self._people_usd_short(t["rev"]),
                "ratio": "%s%%" % ratio12, "tones": {}})
            pcr_popup = self._people_month_table(
                "people_pcr_table", _("People cost vs revenue"), pcr_rows,
                [{"key": "people", "label": _("People cost"),
                  "format": "money"},
                 {"key": "rev", "label": _("Revenue"), "format": "money"},
                 {"key": "ratio", "label": _("Cost ÷ revenue"),
                  "format": "money"}],
                _("Bonus months can top 100% on paper — the year's bonuses "
                  "book in one month."))
            pcr_points = [{
                "label": m["label"],
                "line": round(m["rev"] / 1000.0, 1),
                "bar": round(m["people"] / 1000.0, 1),
                "domain": [],
                "modal_table": pcr_popup,
            } for m in ledger["series"]]
            pcr_chart = {
                "id": "people_cost_rev", "name": _("People Cost vs Revenue"),
                "type": "combo", "model": "", "mode": "computed",
                "measure": _("USD thousands"), "groupby": _("Month"),
                "color": TEAL,
                "help": _("Bars = people cost, line = revenue, USD thousands"
                          "%(ic)s. Trailing-12: people cost is %(r)s%% of "
                          "revenue. Click for the table.") % {
                    "ic": "" if company_id else _(", intercompany out"),
                    "r": ratio12},
                "value": float(ratio12), "format": "number", "domain": [],
                "points": pcr_points, "rows": [], "columns": [], "span": 6,
                "error": False, "modal_table": pcr_popup,
                "label_line": _("Revenue"), "label_bar": _("People cost"),
            }
            money += [share_chart, pcr_chart]

            # payroll / coverage / cost-per-head KPI row
            factors = ledger["factors"]

            def mUSD(p):
                return (p["wage"] or 0) * factors.get(p["company_id"], 1.0)

            priced = [p for p in people if (p.get("wage") or 0) > 0]
            payroll_month = sum(mUSD(p) for p in priced)
            payroll_year = payroll_month * PEOPLE_MONTHS
            top5 = sorted(priced, key=lambda p: -mUSD(p))[:5]
            top5_share = (round(sum(mUSD(p) for p in top5)
                                / payroll_month * 100)
                          if payroll_month else 0)
            payroll_popup = self._people_roster(
                "people_payroll_list", _("Payroll — per person (USD/mo)"),
                self._people_person_rows(
                    sorted(priced, key=lambda p: -mUSD(p)),
                    lambda p: _("%s/mo") % self._people_usd_short(mUSD(p))),
                _("Monthly (USD)"),
                _("Everyone with pay loaded, highest first. The top 5 take "
                  "%s%% of the total.") % top5_share + " " + scope_note)
            if priced:
                payroll_kpi = self._people_kpi(
                    "people_payroll", _("Team Payroll (loaded)"),
                    round(payroll_year), "usd",
                    _("%(n)s of %(t)s priced · %(m)s/mo · top-5 take "
                      "%(x)s%%") % {
                        "n": len(priced), "t": headcount,
                        "m": self._people_usd_short(payroll_month),
                        "x": top5_share}, TEAL,
                    _("Annualised payroll from wages entered in Odoo, USD at "
                      "today's rates. SA & Indonesia join as their pay goes "
                      "in. Click for the per-person list.") + " "
                    + scope_note,
                    span=4, modal_table=payroll_popup,
                    value_text=self._people_usd_short(payroll_year))
            else:
                payroll_kpi = self._people_kpi(
                    "people_payroll", _("Team Payroll"), 0, "integer",
                    _("no wages entered in Odoo yet"), AMBER,
                    _("Once wages are entered, payroll, salary coverage and "
                      "cost per department light up — group-wide in USD."),
                    span=4)

            if coverage and coverage["rows"]:
                team_value = sum(r["value"] for r in coverage["rows"])
                team_salary = sum(r["salary"] for r in coverage["rows"])
                team_cov = (team_value / team_salary) if team_salary else 0.0
                cov_rows = [{
                    "label": r["name"],
                    "domain": self._json_safe([("id", "in", r["line_ids"])]),
                    "model": "account.analytic.line",
                    "value": self._people_usd_short(r["value"]),
                    "salary": self._people_usd_short(r["salary"]),
                    "cov": "%.1f×" % (r["cov"] / 100.0),
                    "tones": {"cov": "good" if r["cov"] >= 200
                              else "warn" if r["cov"] >= 100 else "bad"},
                } for r in coverage["rows"]]
                cov_rows.append({
                    "label": _("Team total"), "domain": [],
                    "value": self._people_usd_short(team_value),
                    "salary": self._people_usd_short(team_salary),
                    "cov": "%.1f×" % team_cov, "tones": {}})
                cov_popup = self._people_matrix(
                    "people_cov_table",
                    _("Salary coverage — %s, per person") % coverage["label"],
                    cov_rows,
                    [{"key": "value", "label": _("Billable value"),
                      "format": "money"},
                     {"key": "salary", "label": _("Salary"),
                      "format": "money"},
                     {"key": "cov", "label": _("Coverage"),
                      "format": "money"}],
                    _("Billable hours valued at the T&M sale-line rate, "
                      "else at the trailing blended rate. A row opens the "
                      "person's time entries."),
                    _("Person"))
                cov_kpi = self._people_kpi(
                    "people_team_coverage", _("Team Salary Coverage"),
                    round(team_cov * 100), "percent",
                    _("%s · delivery team, billable value ÷ payroll")
                    % coverage["label"],
                    GREEN if team_cov >= 2 else AMBER if team_cov >= 1
                    else RED,
                    _("How many times over the delivery team's billable "
                      "value covers its own payroll. Click for the "
                      "per-person multiples — same math as the Salary "
                      "Coverage chart on the Aurika Ops Dashboard."),
                    span=4, value_text="%.1f×" % team_cov,
                    modal_table=cov_popup)
            else:
                cov_kpi = self._people_kpi(
                    "people_team_coverage", _("Team Salary Coverage"), 0,
                    "integer", _("needs wages + billable data"), AMBER,
                    _("Lights up once wages are loaded and billable "
                      "timesheets exist."), span=4)

            avg_heads = (series[0]["hc"] + series[-1]["hc"]) / 2.0 or 1.0
            cost_head = t["op"] / avg_heads if t["op"] else 0.0
            margin_head = rev_head - cost_head
            ch_popup = self._people_matrix(
                "people_costhead_table",
                _("All-in cost per head — the math"),
                [
                    {"label": _("Total operating cost, trailing 12 months"),
                     "domain": [], "val": self._people_usd_short(t["op"]),
                     "tones": {}},
                    {"label": _("Average headcount over the window"),
                     "domain": [], "val": "≈ %.1f" % avg_heads, "tones": {}},
                    {"label": _("All-in cost per head per year"),
                     "domain": [], "val": self._people_usd_short(cost_head),
                     "tones": {}},
                    {"label": _("Revenue per head (same window)"),
                     "domain": [], "val": self._people_usd_short(rev_head),
                     "tones": {}},
                    {"label": _("Margin per head"), "domain": [],
                     "val": self._people_usd_short(margin_head),
                     "tones": {"val": "good" if margin_head >= 0
                               else "bad"}},
                ],
                [{"key": "val", "label": _("Value"), "format": "money"}],
                _("Each new hire must bring more than the all-in figure in "
                  "extra revenue to pay for their seat."),
                _("Step"))
            ch_kpi = self._people_kpi(
                "people_cost_head", _("All-in Cost per Head"),
                round(cost_head), "usd",
                _("per person per year, everything included"), TEAL,
                _("Total overheads ÷ average headcount, trailing 12 months. "
                  "Revenue per head is %s — the margin per head is the gap. "
                  "Click for the math.") % self._people_usd_short(rev_head),
                span=4, modal_table=ch_popup,
                value_text=self._people_usd_short(cost_head))
            money += [payroll_kpi, cov_kpi, ch_kpi]

            # cost by department
            if priced:
                dept_cost = {}
                for p in priced:
                    key = p["dept"] or _("No department")
                    entry = dept_cost.setdefault(key, {"usd": 0.0,
                                                       "members": []})
                    entry["usd"] += mUSD(p) * PEOPLE_MONTHS
                    entry["members"].append(p)
                dept_points = []
                for name, entry in sorted(dept_cost.items(),
                                          key=lambda kv: -kv[1]["usd"]):
                    dept_points.append({
                        "label": name, "value": round(entry["usd"]),
                        "color": TEAL,
                        "domain": self._json_safe([
                            ("id", "in", [eid for p in entry["members"]
                                          for eid in p["emp_ids"]])]),
                        "modal_table": self._people_roster(
                            "people_costdept_%s" % re.sub(
                                r"\W+", "_", name.lower()),
                            _("%s — cost per person") % name,
                            self._people_person_rows(
                                sorted(entry["members"],
                                       key=lambda p: -mUSD(p)),
                                lambda p: _("%s/yr") % self._people_usd_short(
                                    mUSD(p) * PEOPLE_MONTHS)),
                            _("Annual (USD)"),
                            _("Cost of each person in %s.") % name),
                    })
                money.append(self._people_bar(
                    "people_cost_dept", _("Cost by Department (USD/yr)"),
                    dept_points,
                    _("Annual payroll by team from loaded wages, USD. Click "
                      "a bar for the people.") + " " + scope_note,
                    _("Cost"), _("Department"), span=6, fmt="usd"))

        # ---- time off (with the zero-leave watch) ----
        period_leaves = [l for l in data["leaves"]
                         if str(start) <= l["date"] <= str(end)]
        total_days = sum(l["days"] for l in period_leaves)
        by_type = {}
        for l in period_leaves:
            entry = by_type.setdefault(l["type"], {"days": 0.0, "ids": [],
                                                   "id": l["type_id"]})
            entry["days"] += l["days"]
            entry["ids"].append(l["id"])
        type_sorted = sorted(by_type.items(),
                             key=lambda kv: -kv[1]["days"])[:6]
        leave_points = [{
            "label": name,
            "value": round(entry["days"]),
            "color": AMBER if "sick" in name.lower() else TEAL,
            "domain": self._json_safe([("id", "in", entry["ids"])]),
        } for name, entry in type_sorted]
        working_days = max(1, (end - start).days / 365.25 * 250)
        absence = round(total_days / (headcount * working_days) * 100, 1) \
            if headcount else 0.0
        six_months_ago = today - timedelta(days=180)
        zero_leave = sorted(
            p["name"] for p in people
            if (self._people_safe_date(p["join"])
                or fields.Date.to_date("1900-01-01")) < six_months_ago
            and data["leave_by_person"].get(p["pid"], 0.0) <= 0.0)
        watch = (" " + _("Zero leave in the window (burnout watch): %s.")
                 % " · ".join(zero_leave[:8]) if zero_leave else "")
        leave_bar = self._people_bar(
            "people_leave", _("Time Off & Wellbeing"), leave_points,
            _("Approved leave over %(p)s — %(d)s days, ≈%(a)s%% absence.") % {
                "p": period_label, "d": round(total_days), "a": absence}
            + watch + " " + scope_note,
            _("Days"), _("Leave type"), model="hr.leave", span=6)
        money += [leave_bar]

        # ---- retention (true leavers) ----
        retention = [self._people_sechead(
            "people_sec_retain", _("Retention — the honest version"))]
        exit_points = []
        for m in series:
            month_leavers = [d for d in departed
                             if d["date"][:7] == "%04d-%02d" % m["key"]]
            exit_points.append({
                "label": m["label"], "value": len(month_leavers),
                "color": RED if len(month_leavers) >= 3 else
                AMBER if len(month_leavers) == 2 else TEAL,
                "domain": self._json_safe(
                    [("id", "in", [d["emp_id"] for d in month_leavers])]),
                "detail": None,
                "modal_table": self._people_roster(
                    "people_exit_%04d_%02d" % m["key"],
                    _("Left in %s") % m["label"],
                    self._people_leaver_rows(
                        month_leavers,
                        lambda d: "%s · %s" % (leaver_when(d), d["reason"])),
                    _("Left on · reason"),
                    _("Real leavers only — duplicate cards are "
                      "quarantined."))
                if month_leavers else False,
            })
        exits_chart = self._people_column(
            "people_exits_monthly", _("Real Exits, Month by Month"),
            exit_points,
            _("Who actually left, when — %(ph)s phantom cards excluded. "
              "Click a bar for the names.") % {"ph": len(phantoms)}
            + " " + scope_note,
            _("Leavers"), _("Month"), model="hr.employee", span=6,
            color=RED)

        def exit_tenure(d):
            j = self._people_safe_date(d["join"])
            dp = self._people_safe_date(d["date"])
            if j and dp:
                return (dp - j).days / 365.25
            return None

        stay_defs = [(_("< 1 yr"), 0, 1), (_("1–2 yrs"), 1, 2),
                     (_("2–5 yrs"), 2, 5), (_("5+ yrs"), 5, 999)]
        exit_ten = [(d, exit_tenure(d)) for d in exits]
        early = [d for d, y in exit_ten if y is not None and y < 1]
        stay_points = []
        shades = [RED, "#d08a2e", "#3a97a0", TEAL]
        for i, (label, lo, hi) in enumerate(stay_defs):
            members = [d for d, y in exit_ten
                       if y is not None and lo <= y < hi]
            stay_points.append({
                "label": label, "value": len(members), "color": shades[i],
                "domain": self._json_safe(
                    [("id", "in", [d["emp_id"] for d in members])]),
                "modal_table": self._people_roster(
                    "people_stay_%d" % i, _("Stayed %s") % label,
                    self._people_leaver_rows(
                        sorted(members, key=lambda d: d["date"],
                               reverse=True),
                        lambda d: _("%(w)s · stayed %(y)s yrs") % {
                            "w": leaver_when(d),
                            "y": round(exit_tenure(d) or 0, 1)}),
                    _("Left on · stay"),
                    _("Real leavers who stayed %s.") % label)
                if members else False,
            })
        early_bar = self._people_bar(
            "people_early_exits", _("How Early Do Leavers Leave?"),
            stay_points,
            _("Tenure at exit, real leavers, %(p)s: %(e)s of %(n)s left "
              "inside their first year. Click a row for who.") % {
                "p": period_label, "e": len(early), "n": len(exits)}
            + " " + scope_note,
            _("Leavers"), _("Tenure at exit"), span=3)

        reasons = {}
        for d in exits:
            reasons.setdefault(d["reason"], []).append(d)
        reason_points = []
        for i, (name, members) in enumerate(
                sorted(reasons.items(), key=lambda kv: -len(kv[1]))):
            reason_points.append({
                "label": name, "value": len(members),
                "color": RED if i == 0 else AMBER if i == 1 else TEAL,
                "domain": self._json_safe(
                    [("id", "in", [d["emp_id"] for d in members])]),
                "modal_table": self._people_roster(
                    "people_reason_%d" % i, _("Left: %s") % name,
                    self._people_leaver_rows(
                        sorted(members, key=lambda d: d["date"],
                               reverse=True),
                        leaver_when),
                    _("Left on"),
                    _("Real leavers with reason '%s'.") % name),
            })
        reasons_bar = self._people_bar(
            "people_reasons", _("Why People Really Leave"), reason_points,
            _("Recorded reasons of real leavers over %s — resignations are "
              "the regretted ones. Click a row for who.") % period_label
            + " " + scope_note,
            _("Leavers"), _("Reason"), span=3)
        retention += [exits_chart, early_bar, reasons_bar]

        # ---- shape ----
        dept = {}
        for p in people:
            key = p["dept"] or _("No department")
            entry = dept.setdefault(key, {"n": 0, "id": p["dept_id"]})
            entry["n"] += 1
        dept_points = []
        for name, entry in sorted(dept.items(), key=lambda kv: -kv[1]["n"]):
            members = [p for p in people
                       if (p["dept"] or _("No department")) == name]
            dept_points.append({
                "label": name, "value": entry["n"], "color": TEAL,
                "domain": self._json_safe(
                    [("department_id", "=", entry["id"]),
                     ("active", "=", True)]
                    if entry["id"] else
                    [("department_id", "=", False), ("active", "=", True)]),
                "modal_table": self._people_roster(
                    "people_dept_%s" % (entry["id"] or "none"),
                    _("%s — team") % name,
                    self._people_person_rows(
                        sorted(members, key=lambda p: p["name"]), _yrs),
                    _("Tenure"),
                    _("Everyone in %s.") % name),
            })
        dept_bar = self._people_bar(
            "people_departments", _("Where Everyone Sits"), dept_points,
            _("Headcount by department. Click a bar for the team.") + " "
            + scope_note,
            _("People"), _("Department"), span=6)

        person_years = [(p, self._people_years(p["join"], today))
                        for p in people]
        ten_defs = [(_("< 1 yr"), 0, 1), (_("1–2 yrs"), 1, 2),
                    (_("2–5 yrs"), 2, 5), (_("5–10 yrs"), 5, 10),
                    (_("10+ yrs"), 10, 999)]
        ten_points = []
        ten_shades = ["#0f6b74", "#1a7f89", "#3a97a0", "#6bb3ba", "#9ccbd0"]
        for i, (label, lo, hi) in enumerate(ten_defs):
            members = [p for p, y in person_years
                       if y is not None and lo <= y < hi]
            ten_points.append({
                "label": label, "value": len(members),
                "color": ten_shades[i],
                "domain": [], "detail": None,
                "modal_table": self._people_roster(
                    "people_tenure_b%d" % i, _("Tenure %s") % label,
                    self._people_person_rows(
                        sorted(members, key=lambda p: p["name"]), _yrs),
                    _("Tenure"),
                    _("Everyone with %s of tenure.") % label)
                if members else False,
            })
        tenure_col = self._people_column(
            "people_tenure_dist", _("Tenure & Age Mix"), ten_points,
            _("How long people have been here. Median age %(a)s · %(m)s "
              "birthdays missing%(b)s. Click a bar for who.") % {
                "a": round(median_age) if ages else "—",
                "m": no_birthday,
                "b": (_(", %s impossible") % bad_birthday if bad_birthday
                      else "")} + " " + scope_note,
            _("People"), _("Tenure"), span=6)

        widgets = [chips] + hero + [
            self._people_sechead("people_sec_growth", _("The growth story")),
            hc_chart, confidence,
        ] + money + retention + [
            self._people_sechead("people_sec_shape", _("Shape of the team")),
            dept_bar, tenure_col,
        ]
        return widgets
