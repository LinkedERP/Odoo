import re
from datetime import timedelta

from odoo import api, fields, models, _

FIN_DASHBOARD_NAME = "Aurika Finance Dashboard"

# EBITDA ingredient mapping: expense accounts are split out of overheads by
# NAME (kept as patterns so the accountant can rename/extend without data
# migration). Interest EARNED stays inside other income (accepted
# simplification, noted in the ladder help).
FIN_DA_PAT = re.compile(r"deprec|amort", re.IGNORECASE)
FIN_INT_PAT = re.compile(r"\binterest\b", re.IGNORECASE)
FIN_TAX_PAT = re.compile(r"income tax|corporate tax|current tax", re.IGNORECASE)
# Intercompany accounts by naming convention ("IC COGS", "IC FTE ...").
FIN_IC_ACCOUNT_PAT = re.compile(r"^ic\b", re.IGNORECASE)

# Tunable thresholds (spec §4.4).
FIN_GP_GOOD, FIN_GP_WARN = 40.0, 20.0
FIN_EBITDA_GOOD, FIN_EBITDA_WARN = 15.0, 5.0
FIN_DSO_GOOD, FIN_DSO_WARN = 60, 90
FIN_STALE_SHARE_ALERT = 0.30
FIN_COLLECT_GAP_ALERT = 0.85
FIN_CHASE_RED_SHARE, FIN_CHASE_AMBER_SHARE = 0.55, 0.35

FIN_SPARK_MONTHS = 13
FIN_TREND_MONTHS = 8
FIN_COMBO_MONTHS = 6
FIN_CONC_MONTHS = 12
FIN_MONTH_OPTIONS = 18

FIN_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

FIN_AGING_BUCKETS = ["not_due", "b30", "b60", "b90", "over90"]
FIN_AGING_LABELS = {
    "not_due": "Not yet due", "b30": "1–30 days", "b60": "31–60",
    "b90": "61–90", "over90": "Over 90 days",
}
FIN_AGING_COLORS = {
    "not_due": "#94a3b8", "b30": "#1e5b96", "b60": "#d97706",
    "b90": "#d97706", "over90": "#dc2626",
}

FIN_GREEN, FIN_RED, FIN_BLUE = "#059669", "#dc2626", "#1e5b96"


class LinkederpDashboardFinance(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_finance_dashboard()

    def _ensure_finance_dashboard(self):
        if self._ensure_dashboard_name(FIN_DASHBOARD_NAME, []):
            return
        if "account.move" not in self.env:
            return
        self.create(
            {
                "name": FIN_DASHBOARD_NAME,
                "sequence": 70,
                "bucket": "management",
                "description": _(
                    "The MDs' money cockpit: cash, invoicing vs collections, "
                    "receivables ageing, the P&L ladder down to EBITDA, and "
                    "spend — group view in USD with intercompany stripped, "
                    "or any single company's true books."
                ),
                "color": "#1e5b96",
            }
        )

    def _is_finance_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == FIN_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Month / window helpers
    # ------------------------------------------------------------------
    @api.model
    def _fin_month_key(self, value):
        try:
            year, month = str(value).split("-")[:2]
            year, month = int(year), int(month)
        except (TypeError, ValueError):
            return None
        if 1 <= month <= 12 and 2000 <= year <= 2100:
            return (year, month)
        return None

    @api.model
    def _fin_month_str(self, key):
        return "%04d-%02d" % key

    @api.model
    def _fin_month_label(self, value):
        key = self._fin_month_key(value)
        if not key:
            return str(value)
        return "%s '%02d" % (FIN_MONTH_LABELS[key[1] - 1], key[0] % 100)

    @api.model
    def _fin_prev_month(self, key):
        return (key[0] - 1, 12) if key[1] == 1 else (key[0], key[1] - 1)

    @api.model
    def _fin_months_back(self, end_value, count):
        """['YYYY-MM', ...] ascending, `count` months ending at end_value."""
        key = self._fin_month_key(end_value)
        if not key:
            return []
        out = []
        for _i in range(count):
            out.append(self._fin_month_str(key))
            key = self._fin_prev_month(key)
        return list(reversed(out))

    @api.model
    def _fin_month_bounds(self, value):
        key = self._fin_month_key(value)
        start = fields.Date.to_date("%04d-%02d-01" % key)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return start, end

    def _fin_basis_start(self, basis, today):
        """Calendar year: 1 Jan. SA year: 1 Mar (Linked ERP (Pty) Ltd's
        fiscal year runs Mar–Feb — Akshay 2026-07-04; India/Indonesia
        fiscal years intentionally not offered)."""
        if basis == "sa":
            year = today.year if (today.month >= 3) else today.year - 1
            return today.replace(year=year, month=3, day=1)
        return today.replace(month=1, day=1)

    def _fin_ytd_months(self, basis, today):
        start = self._fin_basis_start(basis, today)
        months = []
        key = (start.year, start.month)
        end_key = (today.year, today.month)
        while key <= end_key:
            months.append(self._fin_month_str(key))
            key = (key[0] + 1, 1) if key[1] == 12 else (key[0], key[1] + 1)
        return months

    def _fin_window_label(self, basis, today):
        months = self._fin_ytd_months(basis, today)
        label = _("%(a)s – %(b)s") % {
            "a": self._fin_month_label(months[0]),
            "b": self._fin_month_label(months[-1])}
        if basis == "sa":
            return label + _(" (SA year, Mar–Feb)")
        return label + _(" (calendar year)")

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    def _fin_company_options(self):
        return [{"id": company.id, "name": company.name}
                for company in self.env["res.company"].search([], order="name")]

    def _fin_selected_company(self, filters=False):
        filters = filters or {}
        try:
            value = int(filters.get("fin_company_id") or 0)
        except (TypeError, ValueError):
            value = 0
        if value in {c["id"] for c in self._fin_company_options()}:
            return value
        return 0

    def _fin_selected_basis(self, filters=False):
        filters = filters or {}
        value = str(filters.get("fin_basis") or "")
        return value if value in ("cal", "sa") else "cal"

    def _fin_default_month(self, today):
        """The last COMPLETED calendar month."""
        first = today.replace(day=1)
        prev = first - timedelta(days=1)
        return self._fin_month_str((prev.year, prev.month))

    def _fin_month_options(self, today):
        options = [{"value": "", "label": _("Latest full month")}]
        key = (today.year, today.month)
        for _i in range(FIN_MONTH_OPTIONS):
            value = self._fin_month_str(key)
            options.append({"value": value,
                            "label": self._fin_month_label(value)})
            key = self._fin_prev_month(key)
        return options

    def _fin_selected_month(self, filters, today):
        filters = filters or {}
        value = str(filters.get("fin_month") or "")
        if value and any(o["value"] == value
                         for o in self._fin_month_options(today)):
            return value
        return ""

    def _fin_filter_options(self, filters=False):
        today = fields.Date.context_today(self)
        return {
            "enabled": True,
            "company": self._fin_selected_company(filters) or "",
            "companies": self._fin_company_options(),
            "basis": self._fin_selected_basis(filters),
            "bases": [
                {"value": "cal", "label": _("Calendar year")},
                {"value": "sa", "label": _("SA year (Mar–Feb)")},
            ],
            "month": self._fin_selected_month(filters, today),
            "months": self._fin_month_options(today),
        }

    # ------------------------------------------------------------------
    # Currency & intercompany
    # ------------------------------------------------------------------
    def _fin_usd_factors(self, usd, today, companies):
        """{company_id: USD per 1 unit of the company currency} at the
        newest stored rates (learning #14: derive per company, never
        hardcode a snapshot)."""
        factors = {}
        for company in companies:
            try:
                factors[company.id] = company.currency_id._convert(
                    1.0, usd, company, today, round=False)
            except Exception:
                factors[company.id] = 1.0
        return factors

    @api.model
    def _fin_clean_account(self, name):
        cleaned = re.sub(r"\s*\(copy\)", "", name or "")
        cleaned = re.sub(r"^\d{4,6}\s+", "", cleaned).strip()
        return cleaned or _("Unnamed account")

    def _fin_account_buckets(self):
        """({account_id: bucket}, {account_id: cleaned name},
        {'cash': ids, 'receivable': ids}). Buckets: rev/oth/dc/da/int/
        tax/opex; non-P&L types are absent from the bucket map."""
        buckets, names = {}, {}
        special = {"cash": [], "receivable": []}
        for account in self.env["account.account"].search([]):
            acc_type = account.account_type
            cleaned = self._fin_clean_account(account.name)
            names[account.id] = cleaned
            if acc_type == "asset_cash":
                special["cash"].append(account.id)
                continue
            if acc_type == "asset_receivable":
                special["receivable"].append(account.id)
                continue
            if acc_type == "income":
                buckets[account.id] = "rev"
            elif acc_type == "income_other":
                buckets[account.id] = "oth"
            elif acc_type == "expense_direct_cost":
                buckets[account.id] = "dc"
            elif str(acc_type).startswith("expense"):
                if FIN_DA_PAT.search(cleaned) or acc_type == "expense_depreciation":
                    buckets[account.id] = "da"
                elif FIN_INT_PAT.search(cleaned):
                    buckets[account.id] = "int"
                elif FIN_TAX_PAT.search(cleaned):
                    buckets[account.id] = "tax"
                else:
                    buckets[account.id] = "opex"
        return buckets, names, special

    # ------------------------------------------------------------------
    # Collector
    # ------------------------------------------------------------------
    def _fin_collect(self, company_id, today, usd):
        """One pull of everything the widgets need. Rows keep an `ic`
        flag; the group view excludes IC rows, a single-company view
        keeps them (true books). `company_id` = 0 means group. Customer
        invoices are deliberately unfloored: open receivables can be
        arbitrarily old (volumes are small; the validator's timing check
        guards the budget)."""
        companies = self.env["res.company"].search([])
        company_names = {c.id: c.name for c in companies}
        factors = self._fin_usd_factors(usd, today, companies)
        # A company currency with NO stored USD rate converts 1:1 and
        # would silently produce absurd group numbers — surface it.
        rate_warnings = [
            c.name for c in companies
            if usd and c.currency_id and c.currency_id.id != usd.id
            and abs(factors.get(c.id, 1.0) - 1.0) < 1e-9]
        ic_partners = set(companies.mapped("partner_id").ids)
        buckets, names, special = self._fin_account_buckets()

        company_domain = [("company_id", "=", company_id)] if company_id else []
        current_month = self._fin_month_str((today.year, today.month))
        # The month filter reaches FIN_MONTH_OPTIONS back and each chart
        # window extends FIN_SPARK_MONTHS further — fetch far enough that
        # ANY selectable month has full chart history.
        spark_start = "%s-01" % self._fin_months_back(
            current_month, FIN_MONTH_OPTIONS + FIN_SPARK_MONTHS)[0]
        basis_floor = min(
            spark_start,
            str(self._fin_basis_start("cal", today)),
            str(self._fin_basis_start("sa", today)))

        def usd_of(cid, amount):
            return (amount or 0.0) * factors.get(cid, 1.0)

        Move = self.env["account.move"]
        inv_fields = ["name", "invoice_date", "invoice_date_due",
                      "amount_total_signed", "amount_residual_signed",
                      "amount_total", "currency_id", "company_id",
                      "payment_state", "commercial_partner_id",
                      "invoice_payment_term_id"]
        inv_base = [("move_type", "in", ["out_invoice", "out_refund"]),
                    ("state", "=", "posted")] + company_domain
        # Two pulls merged by id: OPEN invoices at any age (receivables can
        # be arbitrarily old) + everything inside the charting window — so
        # history growth cannot blow the payload budget.
        raw_moves = {}
        for move in Move.search_read(
                inv_base + [("payment_state", "in", ["not_paid", "partial"])],
                inv_fields):
            raw_moves[move["id"]] = move
        for move in Move.search_read(
                inv_base + [("invoice_date", ">=", spark_start)], inv_fields):
            raw_moves[move["id"]] = move
        invoices = []
        for move in raw_moves.values():
            cid = move["company_id"] and move["company_id"][0] or 0
            partner = move["commercial_partner_id"] or (0, _("Unknown"))
            inv_date = move["invoice_date"]
            invoices.append({
                "id": move["id"],
                "name": move["name"] or "?",
                "month": str(inv_date)[:7] if inv_date else "",
                "date": inv_date,
                "due": move["invoice_date_due"] or inv_date,
                "partner_id": partner[0],
                "partner": partner[1],
                "company_id": cid,
                "usd": usd_of(cid, move["amount_total_signed"]),
                "residual_usd": usd_of(cid, move["amount_residual_signed"]),
                "native": move["amount_total"] or 0.0,
                "ccy": move["currency_id"] and move["currency_id"][1] or "",
                "state": move["payment_state"],
                "ic": partner[0] in ic_partners,
                "has_terms": bool(move["invoice_payment_term_id"]),
            })

        bank_journal_ids = self.env["account.journal"].search(
            [("type", "in", ["bank", "cash"])]).ids
        Line = self.env["account.move.line"]
        raw_credits = Line.search_read(
            [("account_id", "in", special["receivable"]),
             ("parent_state", "=", "posted"), ("credit", ">", 0),
             ("journal_id", "in", bank_journal_ids),
             ("date", ">=", spark_start)] + company_domain,
            ["date", "credit", "company_id", "partner_id"])
        partner_ids = sorted({r["partner_id"][0] for r in raw_credits
                              if r["partner_id"]})
        commercial = {}
        if partner_ids:
            for partner in self.env["res.partner"].browse(partner_ids):
                root = partner.commercial_partner_id or partner
                commercial[partner.id] = (root.id, root.name or "?")
        collections = []
        for row in raw_credits:
            cid = row["company_id"] and row["company_id"][0] or 0
            pid, pname = commercial.get(
                row["partner_id"] and row["partner_id"][0] or 0,
                (0, _("(no partner)")))
            collections.append({
                "month": str(row["date"])[:7],
                "date": row["date"],
                "partner": pname,
                "company_id": cid,
                "usd": usd_of(cid, row["credit"]),
                "ic": pid in ic_partners,
            })

        # P&L lines are pre-aggregated to (month, account, company, ic)
        # sums so the many downstream ladder scans iterate a few hundred
        # rows instead of every posted move line.
        pl_totals = {}
        if buckets:
            for row in Line.search_read(
                    [("account_id", "in", list(buckets)),
                     ("parent_state", "=", "posted"),
                     ("date", ">=", basis_floor)] + company_domain,
                    ["date", "balance", "company_id", "account_id",
                     "partner_id"]):
                cid = row["company_id"] and row["company_id"][0] or 0
                account_id = row["account_id"][0]
                cleaned = names.get(account_id, "?")
                pid = row["partner_id"] and row["partner_id"][0] or 0
                key = (str(row["date"])[:7], account_id, cid,
                       pid in ic_partners
                       or bool(FIN_IC_ACCOUNT_PAT.match(cleaned)))
                pl_totals[key] = pl_totals.get(key, 0.0) \
                    + usd_of(cid, row["balance"])
        pl = [{
            "month": month, "bucket": buckets[account_id],
            "account_id": account_id, "account": names.get(account_id, "?"),
            "company_id": cid, "usd": total, "ic": ic,
        } for (month, account_id, cid, ic), total in pl_totals.items()]

        cash_rows = []
        if special["cash"]:
            currencies = {c.id: c.currency_id for c in companies}
            for row in Line.read_group(
                    [("account_id", "in", special["cash"]),
                     ("parent_state", "=", "posted")] + company_domain,
                    ["balance:sum", "date:max"],
                    ["account_id", "company_id"], lazy=False):
                cid = row["company_id"] and row["company_id"][0] or 0
                account_id = row["account_id"] and row["account_id"][0] or 0
                balance = row.get("balance", 0.0) or 0.0
                if abs(balance) < 0.01:
                    continue
                cash_rows.append({
                    "company_id": cid,
                    "company": company_names.get(cid, "?"),
                    "account_id": account_id,
                    "account": names.get(account_id, "?"),
                    "native_text": self._ops_money(
                        balance, currencies.get(cid) or usd),
                    "usd": usd_of(cid, balance),
                    "last": str(row.get("date") or "")[:10],
                })

        ap_bills = []
        for move in Move.search_read(
                [("move_type", "in", ["in_invoice", "in_refund"]),
                 ("state", "=", "posted"),
                 ("payment_state", "in", ["not_paid", "partial"])]
                + company_domain,
                ["name", "invoice_date", "amount_residual_signed",
                 "company_id", "commercial_partner_id"]):
            cid = move["company_id"] and move["company_id"][0] or 0
            partner = move["commercial_partner_id"] or (0, _("Unknown"))
            ap_bills.append({
                "id": move["id"],
                "name": move["name"] or "?",
                "date": move["invoice_date"],
                "partner": partner[1],
                "usd": -usd_of(cid, move["amount_residual_signed"]),
                "ic": partner[0] in ic_partners,
            })

        unreconciled = 0
        if "account.bank.statement.line" in self.env:
            unreconciled = self.env["account.bank.statement.line"].search_count(
                [("is_reconciled", "=", False)] + company_domain)
        copy_accounts = self.env["account.account"].search_count(
            [("name", "like", "(copy)")])

        return {
            "companies": [(c.id, c.name) for c in companies],
            "rate_warnings": rate_warnings,
            "ic_partners": ic_partners,
            "invoices": invoices,
            "collections": collections,
            "pl": pl,
            "cash_rows": cash_rows,
            "ap_bills": ap_bills,
            "receivable_ids": special["receivable"],
            "bank_journal_ids": bank_journal_ids,
            "hyg": {
                "no_terms": sum(1 for i in invoices if not i["has_terms"]),
                "inv_total": len(invoices),
                "unrec": unreconciled,
                "copy_accounts": copy_accounts,
            },
        }

    # ------------------------------------------------------------------
    # Aggregation helpers (all operate on collected rows + a keep() rule)
    # ------------------------------------------------------------------
    @api.model
    def _fin_keep(self, company_id):
        """Group view: intercompany stripped. Single company: true books."""
        if company_id:
            return lambda row: True
        return lambda row: not row["ic"]

    def _fin_invoiced_in(self, data, keep, month):
        return sum(i["usd"] for i in data["invoices"]
                   if i["month"] == month and keep(i))

    def _fin_collected_in(self, data, keep, month):
        return sum(c["usd"] for c in data["collections"]
                   if c["month"] == month and keep(c))

    def _fin_open_invoices(self, data, keep):
        return [i for i in data["invoices"]
                if i["state"] in ("not_paid", "partial")
                and abs(i["residual_usd"]) > 0.005 and keep(i)]

    @api.model
    def _fin_aging_bucket(self, days):
        if days <= 0:
            return "not_due"
        if days <= 30:
            return "b30"
        if days <= 60:
            return "b60"
        if days <= 90:
            return "b90"
        return "over90"

    def _fin_ladder_values(self, data, keep, months, company_id=0):
        """Bucket sums over `months`. `company_id` narrows to one company's
        rows WITHOUT the IC rule (per-company true books inside the group
        view)."""
        month_set = set(months)
        totals = {b: 0.0 for b in ("rev", "oth", "dc", "opex", "da", "int", "tax")}
        for row in data["pl"]:
            if row["month"] not in month_set:
                continue
            if company_id:
                if row["company_id"] != company_id:
                    continue
            elif not keep(row):
                continue
            totals[row["bucket"]] += row["usd"]
        rev = -totals["rev"]
        oth = -totals["oth"]
        dc, opex = totals["dc"], totals["opex"]
        da, intr, tax = totals["da"], totals["int"], totals["tax"]
        gp = rev - dc
        ebitda = gp + oth - opex
        return {"rev": rev, "oth": oth, "dc": dc, "opex": opex, "da": da,
                "int": intr, "tax": tax, "gp": gp, "ebitda": ebitda,
                "net": ebitda - da - intr - tax}

    @api.model
    def _fin_usd_short(self, value):
        sign = "−" if value < 0 else ""
        amount = abs(value or 0.0)
        if amount >= 999.5:
            return "%s$%sK" % (sign, "{:,.0f}".format(round(amount / 1000.0)))
        return "%s$%s" % (sign, "{:,.0f}".format(round(amount)))

    @api.model
    def _fin_pct_of(self, part, whole):
        if not whole:
            return None
        return round(part / whole * 100.0, 1)

    @api.model
    def _fin_tone(self, value, good_from, warn_from):
        if value is None:
            return ""
        if value >= good_from:
            return "good"
        if value >= warn_from:
            return "warn"
        return "bad"

    # ------------------------------------------------------------------
    # Widget primitives
    # ------------------------------------------------------------------
    def _fin_kpi(self, wid, name, value, fmt, caption, color, help_text,
                 model="", domain=None, modal_table=False, points=None,
                 delta=False, scale=False, hero=False, span=3):
        return {
            "id": wid, "name": name, "type": "kpi",
            "model": model, "mode": "computed",
            "measure": caption, "groupby": "", "color": color,
            "help": help_text, "value": float(value), "format": fmt,
            "domain": self._json_safe(domain or []),
            "points": points or [], "rows": [], "columns": [],
            "span": span, "error": False,
            "modal_table": modal_table, "delta": delta, "scale": scale,
            "hero": hero,
        }

    def _fin_matrix(self, wid, name, rows, columns, help_text, groupby,
                    model="", domain=None, span=12, compact=True,
                    color=FIN_BLUE):
        widget = self._sales_matrix(wid, name, rows, columns, help_text,
                                    groupby, span=span, compact=compact,
                                    color=color)
        widget["model"] = model
        widget["domain"] = self._json_safe(domain or [])
        return widget

    def _fin_sechead(self, wid, name):
        return {
            "id": wid, "name": name, "type": "sechead",
            "model": "", "mode": "computed", "measure": "", "groupby": "",
            "color": FIN_BLUE, "help": "", "value": 0.0, "format": "integer",
            "domain": [], "points": [], "rows": [], "columns": [],
            "span": 12, "error": False,
        }

    def _fin_delta(self, current, previous):
        if not previous:
            return False
        pct = round((current - previous) / abs(previous) * 100.0)
        if pct >= 0:
            return {"text": "▲ %d%%" % pct, "dir": "up"}
        return {"text": "▼ %d%%" % abs(pct), "dir": "down"}

    def _fin_spark_points(self, months, value_of):
        return [{"label": self._fin_month_label(month),
                 "value": round(value_of(month)), "domain": [],
                 "detail": None, "color": FIN_BLUE}
                for month in months]

    def _fin_ladder_rows(self, values):
        """Shared ladder line definitions (widget rows AND popup matrices)."""
        rev = values["rev"]
        return [
            {"key": "rev", "label": _("Revenue"), "value": values["rev"],
             "kind": ""},
            {"key": "dc", "label": _("− Direct delivery costs"),
             "value": -values["dc"], "kind": ""},
            {"key": "gp", "label": _("= Gross profit"), "value": values["gp"],
             "pct": self._fin_pct_of(values["gp"], rev),
             "tone_rule": "gp", "kind": "bold"},
            {"key": "oth", "label": _("+ Other income"),
             "value": values["oth"], "kind": ""},
            {"key": "opex", "label": _("− Overheads"),
             "value": -values["opex"], "kind": ""},
            {"key": "ebitda", "label": _("EBITDA"), "value": values["ebitda"],
             "pct": self._fin_pct_of(values["ebitda"], rev),
             "tone_rule": "ebitda", "kind": "hi"},
            {"key": "da", "label": _("− Depreciation"),
             "value": -values["da"], "kind": ""},
            {"key": "int", "label": _("− Interest"),
             "value": -values["int"], "kind": ""},
            {"key": "tax", "label": _("− Corporate tax"),
             "value": -values["tax"], "kind": ""},
            {"key": "net", "label": _("= Net profit"), "value": values["net"],
             "pct": self._fin_pct_of(values["net"], rev), "kind": "bold"},
        ]

    def _fin_row_tone(self, row):
        if row.get("tone_rule") == "gp":
            return self._fin_tone(row.get("pct"), FIN_GP_GOOD, FIN_GP_WARN)
        if row.get("tone_rule") == "ebitda":
            return self._fin_tone(row.get("pct"), FIN_EBITDA_GOOD,
                                  FIN_EBITDA_WARN)
        return ""

    def _fin_ladder_matrix(self, wid, name, values, help_text):
        """A ladder rendered as a popup matrix (month bars, company rows,
        insight popups)."""
        rows = []
        for line in self._fin_ladder_rows(values):
            pct = line.get("pct")
            rows.append({
                "label": line["label"], "domain": [],
                "usd": self._fin_usd_short(line["value"]),
                "pct": self._ops_pct_text(pct) if pct is not None else "",
                "tones": {"usd": "bad" if (line["kind"] in ("hi", "bold")
                                           and line["value"] < 0) else "",
                          "pct": self._fin_row_tone(line)},
            })
        return self._fin_matrix(wid, name, rows, [
            {"key": "usd", "label": _("USD"), "format": "money"},
            {"key": "pct", "label": _("% of revenue"), "format": "money"},
        ], help_text, _("Line"))

    def _fin_ladder_widget(self, wid, name, values, help_text, data, keep,
                           months, scope_note, line_scope):
        rows = []
        for line in self._fin_ladder_rows(values):
            modal = False
            if line["key"] in ("rev", "oth", "dc", "opex", "da", "int", "tax"):
                modal = self._fin_bucket_accounts_matrix(
                    "%s_%s" % (wid, line["key"]), line, data, keep, months,
                    scope_note, line_scope)
            else:
                modal = self._fin_ladder_matrix(
                    "%s_%s" % (wid, line["key"]), name, values, scope_note)
            pct = line.get("pct")
            rows.append({
                "label": line["label"],
                "value": self._fin_usd_short(line["value"]),
                "pct": self._ops_pct_text(pct) if pct is not None else "",
                "tone": self._fin_row_tone(line),
                "kind": line["kind"],
                "neg": bool(line["kind"] in ("hi", "bold")
                            and line["value"] < 0),
                "modal_table": modal,
            })
        return {
            "id": wid, "name": name, "type": "ladder",
            "model": "", "mode": "computed", "measure": "",
            "groupby": _("Line"), "color": FIN_BLUE,
            "help": help_text, "value": float(round(values["net"])),
            "format": "usd", "domain": [], "points": [], "rows": rows,
            "columns": [], "span": 6, "error": False,
        }

    def _fin_bucket_accounts_matrix(self, wid, line, data, keep, months,
                                    scope_note, line_scope):
        """Popup: the accounts behind one ladder bucket, biggest first."""
        month_set = set(months)
        totals = {}
        account_ids = {}
        for row in data["pl"]:
            if row["bucket"] != line["key"] or row["month"] not in month_set:
                continue
            if not keep(row):
                continue
            totals[row["account"]] = totals.get(row["account"], 0.0) + row["usd"]
            account_ids.setdefault(row["account"], set()).add(row["account_id"])
        flip = -1.0 if line["key"] in ("rev", "oth") else 1.0
        start = "%s-01" % months[0]
        _unused, end = self._fin_month_bounds(months[-1])
        rows = []
        for account, value in sorted(totals.items(),
                                     key=lambda kv: -abs(kv[1]))[:20]:
            rows.append({
                "label": account,
                "domain": self._json_safe([
                    ("account_id", "in", sorted(account_ids[account])),
                    ("parent_state", "=", "posted"),
                    ("date", ">=", start), ("date", "<=", str(end))]
                    + line_scope),
                "usd": self._fin_usd_short(flip * value),
                "tones": {},
            })
        return self._fin_matrix(
            wid, _("%s — by account") % line["label"].lstrip("−+= "), rows,
            [{"key": "usd", "label": _("USD"), "format": "money"}],
            scope_note, _("Account"), model="account.move.line")

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------
    def _fin_insight_items(self, data, keep, company_id, today,
                           months_ytd, chart_months, scope_note):
        items = []
        open_invoices = self._fin_open_invoices(data, keep)

        stale = {}
        for invoice in open_invoices:
            if invoice["ic"]:
                continue
            days = (today - fields.Date.to_date(str(invoice["due"]))).days \
                if invoice["due"] else 0
            if days > 90:
                entry = stale.setdefault(
                    invoice["partner"], {"usd": 0.0, "oldest": "9999-12-31",
                                         "ids": []})
                entry["usd"] += invoice["residual_usd"]
                entry["oldest"] = min(entry["oldest"], str(invoice["due"]))
                entry["ids"].append(invoice["id"])
        worst = sorted(stale.items(), key=lambda kv: -kv[1]["usd"])[:1]
        if worst:
            partner, entry = worst[0]
            items.append({
                "sev": "bad", "icon": "fa-phone",
                "title": _("Call %s") % partner,
                "text": _("%(usd)s stuck beyond 90 days — oldest invoice was "
                          "due %(due)s") % {
                    "usd": self._fin_usd_short(entry["usd"]),
                    "due": entry["oldest"]},
                "model": "account.move",
                "domain": self._json_safe([("id", "in", entry["ids"])]),
                "modal_table": False,
            })

        buckets = {b: 0.0 for b in FIN_AGING_BUCKETS}
        bucket_ids = {b: [] for b in FIN_AGING_BUCKETS}
        for invoice in open_invoices:
            days = (today - fields.Date.to_date(str(invoice["due"]))).days \
                if invoice["due"] else 0
            bucket = self._fin_aging_bucket(days)
            buckets[bucket] += invoice["residual_usd"]
            bucket_ids[bucket].append(invoice["id"])
        ar_total = sum(buckets.values())
        if ar_total > 0 and buckets["over90"] / ar_total > FIN_STALE_SHARE_ALERT:
            share = round(buckets["over90"] / ar_total * 100)
            items.append({
                "sev": "bad", "icon": "fa-hourglass-half",
                "title": _("%s%% of receivables have gone stale") % share,
                "text": _("%(part)s of %(total)s owed is more than 90 days "
                          "past due") % {
                    "part": self._fin_usd_short(buckets["over90"]),
                    "total": self._fin_usd_short(ar_total)},
                "model": "account.move",
                "domain": self._json_safe(
                    [("id", "in", bucket_ids["over90"])]),
                "modal_table": False,
            })

        spike = False
        for month in chart_months[-6:]:
            values = self._fin_ladder_values(data, keep, [month])
            if values["rev"] > 0 and values["dc"] > values["rev"]:
                spike = (month, values)
        if spike:
            month, values = spike
            items.append({
                "sev": "warn", "icon": "fa-exclamation-triangle",
                "title": _("%s: delivery costs beat revenue")
                % self._fin_month_label(month),
                "text": _("direct costs %(dc)s vs revenue %(rev)s — click "
                          "for that month's ladder") % {
                    "dc": self._fin_usd_short(values["dc"]),
                    "rev": self._fin_usd_short(values["rev"])},
                "modal_table": self._fin_ladder_matrix(
                    "fin_ins_spike", _("P&L — %s")
                    % self._fin_month_label(month), values, scope_note),
            })

        if not company_id:
            burners = []
            for cid, cname in data["companies"]:
                values = self._fin_ladder_values(
                    data, keep, months_ytd, company_id=cid)
                if values["net"] < 0:
                    burners.append((values["net"], cname, values))
            burners.sort(key=lambda item: item[0])
            if burners:
                _net, cname, values = burners[0]
                items.append({
                    "sev": "warn", "icon": "fa-fire",
                    "title": _("%(name)s is %(usd)s so far") % {
                        "name": cname,
                        "usd": self._fin_usd_short(values["net"])},
                    "text": _("its own books, incl. intercompany — click "
                              "for the company ladder"),
                    "modal_table": self._fin_ladder_matrix(
                        "fin_ins_burn", _("P&L — %s") % cname,
                        values, _("true books incl. intercompany")),
                })

        billed = sum(self._fin_invoiced_in(data, keep, m) for m in months_ytd)
        collected = sum(self._fin_collected_in(data, keep, m)
                        for m in months_ytd)
        if billed > 0 and collected < billed * FIN_COLLECT_GAP_ALERT:
            items.append({
                "sev": "warn", "icon": "fa-exchange",
                "title": _("Billed %(b)s, collected %(c)s") % {
                    "b": self._fin_usd_short(billed),
                    "c": self._fin_usd_short(collected)},
                "text": _("the gap becomes receivables — watch the ageing "
                          "chart below"),
                "modal_table": False,
            })

        cost_months = [m for m in chart_months[-7:-1]]
        costs = []
        for month in cost_months:
            values = self._fin_ladder_values(data, keep, [month])
            total = values["dc"] + values["opex"]
            if total > 0:
                costs.append(total)
        cash_total = sum(r["usd"] for r in data["cash_rows"]
                         if not company_id or r["company_id"] == company_id)
        if costs:
            avg_cost = sum(costs) / len(costs)
            items.append({
                "sev": "good", "icon": "fa-university",
                "title": _("%.1f months of costs in the bank")
                % (cash_total / avg_cost if avg_cost else 0.0),
                "text": _("%(cash)s cash vs ≈%(cost)s average monthly "
                          "costs") % {
                    "cash": self._fin_usd_short(cash_total),
                    "cost": self._fin_usd_short(avg_cost)},
                "modal_table": self._fin_cash_matrix(data, company_id),
            })

        rank = {"bad": 0, "warn": 1, "good": 2}
        items.sort(key=lambda item: rank[item["sev"]])
        return items[:3]

    def _fin_cash_matrix(self, data, company_id):
        rows = []
        for entry in sorted(data["cash_rows"], key=lambda r: -r["usd"]):
            if company_id and entry["company_id"] != company_id:
                continue
            rows.append({
                "label": "%s — %s" % (entry["company"], entry["account"]),
                "domain": self._json_safe([
                    ("account_id", "=", entry["account_id"]),
                    ("parent_state", "=", "posted")]),
                "native": entry["native_text"],
                "usd": self._fin_usd_short(entry["usd"]),
                "last": entry["last"],
                "tones": {},
            })
        return self._fin_matrix(
            "fin_cash_accounts", _("Cash in bank — per account"), rows,
            [
                {"key": "native", "label": _("Own currency"), "format": "money"},
                {"key": "usd", "label": _("USD"), "format": "money"},
                {"key": "last", "label": _("Last bank line"), "format": "text"},
            ],
            _("Posted bank/cash ledger balances at today's rates."),
            _("Account"), model="account.move.line")

    # ------------------------------------------------------------------
    # The dashboard
    # ------------------------------------------------------------------
    def _finance_dashboard_widgets(self, date_from=False, date_to=False,
                                   filters=False):
        if "account.move" not in self.env:
            return [self._fin_kpi(
                "fin_empty", FIN_DASHBOARD_NAME, 0, "integer",
                _("Accounting is not installed."), "#64748b",
                _("Install Invoicing/Accounting to populate this "
                  "dashboard."), span=12)]

        options = self._fin_filter_options(filters)
        company_id = options["company"] or 0
        basis = options["basis"]
        today = fields.Date.context_today(self)
        month = options["month"] or self._fin_default_month(today)
        usd = self._mgmt_usd()
        usd_note = ("" if usd.name == "USD"
                    else _(" ⚠ USD not found — amounts shown in %s.") % usd.name)

        data = self._fin_collect(company_id, today, usd)
        keep = self._fin_keep(company_id)
        ic_ids = sorted(data["ic_partners"])
        # Drill-down record lists must match the displayed sums: scope
        # move-line domains to the company (single-company view) or strip
        # IC-partnered lines (group view; "not in" keeps partner-less
        # lines, matching keep()).
        line_scope = ([("company_id", "=", company_id)] if company_id
                      else [("partner_id.commercial_partner_id",
                             "not in", ic_ids)])
        months_ytd = self._fin_ytd_months(basis, today)
        window_label = self._fin_window_label(basis, today)
        spark_months = self._fin_months_back(month, FIN_SPARK_MONTHS)
        trend_months = self._fin_months_back(month, FIN_TREND_MONTHS)
        combo_months = self._fin_months_back(month, FIN_COMBO_MONTHS)
        conc_months = self._fin_months_back(month, FIN_CONC_MONTHS)
        month_label = self._fin_month_label(month)
        prev_month = self._fin_months_back(month, 2)[0] \
            if len(self._fin_months_back(month, 2)) == 2 else ""

        company_name = ""
        if company_id:
            company_name = self.env["res.company"].browse(company_id).name
        scope_note = (_("Scope: %s (true books, incl. intercompany).")
                      % company_name if company_id
                      else _("Group view — intercompany removed."))

        # ---------------- header chips ----------------
        chips = {
            "id": "fin_header", "name": _("Context"), "type": "chips",
            "model": "", "mode": "computed", "measure": "", "groupby": "",
            "color": FIN_BLUE, "help": "", "value": 0.0, "format": "integer",
            "domain": [], "points": [], "rows": [], "columns": [],
            "span": 12, "error": False,
            "chips": [
                {"icon": "fa-building", "tone": "accent",
                 "text": (company_name or _("All companies (group, USD)"))},
                {"icon": "fa-calendar", "tone": "",
                 "text": _("This year = %s") % window_label},
                {"icon": "fa-calendar-check-o", "tone": "",
                 "text": _("Month cards: %s") % month_label},
                {"icon": "fa-random", "tone": "" if company_id else "good",
                 "text": (_("Includes intercompany") if company_id
                          else _("Intercompany stripped from headlines"))},
            ],
        }
        if data["rate_warnings"]:
            chips["chips"].append({
                "icon": "fa-warning", "tone": "bad",
                "text": _("⚠ No USD rate for %s — those amounts show 1:1")
                % ", ".join(data["rate_warnings"])})

        # ---------------- hero KPIs ----------------
        cash_rows = [r for r in data["cash_rows"]
                     if not company_id or r["company_id"] == company_id]
        cash_total = sum(r["usd"] for r in cash_rows)
        per_company_cash = {}
        for row in data["cash_rows"]:
            per_company_cash[row["company"]] = (
                per_company_cash.get(row["company"], 0.0) + row["usd"])
        cash_caption = (_("as of the last bank line")
                        if company_id else " · ".join(
                            "%s %s" % (name.split()[0],
                                       self._fin_usd_short(value))
                            for name, value in sorted(
                                per_company_cash.items(),
                                key=lambda kv: -kv[1])))

        invoiced_month = self._fin_invoiced_in(data, keep, month)
        invoiced_prev = (self._fin_invoiced_in(data, keep, prev_month)
                         if prev_month else 0.0)
        collected_month = self._fin_collected_in(data, keep, month)
        collected_prev = (self._fin_collected_in(data, keep, prev_month)
                          if prev_month else 0.0)

        open_invoices = self._fin_open_invoices(data, keep)
        ar_total = sum(i["residual_usd"] for i in open_invoices)
        # DSO denominator: 12 COMPLETED months (the partial current month
        # would deflate revenue and overstate DSO early in a month).
        rev_12 = sum(self._fin_invoiced_in(data, keep, m)
                     for m in self._fin_months_back(
                         self._fin_default_month(today), 12))
        dso = round(ar_total / rev_12 * 365) if rev_12 > 0 else 0
        dso_state = (_("healthy") if dso <= FIN_DSO_GOOD
                     else _("watch") if dso <= FIN_DSO_WARN
                     else _("too long"))

        month_start, month_end = self._fin_month_bounds(month)
        month_inv_domain = [
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("state", "=", "posted"),
            ("invoice_date", ">=", str(month_start)),
            ("invoice_date", "<=", str(month_end))]
        collected_domain = [
            ("account_id", "in", data["receivable_ids"]),
            ("parent_state", "=", "posted"), ("credit", ">", 0),
            ("journal_id", "in", data["bank_journal_ids"]),
            ("date", ">=", str(month_start)), ("date", "<=", str(month_end))]
        if company_id:
            month_inv_domain.append(("company_id", "=", company_id))
            collected_domain.append(("company_id", "=", company_id))
        else:
            month_inv_domain.append(
                ("commercial_partner_id", "not in", ic_ids))
            collected_domain.append(
                ("partner_id.commercial_partner_id", "not in", ic_ids))

        ar_rows = []
        for invoice in sorted(open_invoices,
                              key=lambda i: -i["residual_usd"])[:60]:
            days = (today - fields.Date.to_date(str(invoice["due"]))).days \
                if invoice["due"] else 0
            bucket = self._fin_aging_bucket(days)
            ar_rows.append({
                "label": invoice["name"],
                "domain": self._json_safe([("id", "=", invoice["id"])]),
                "partner": invoice["partner"][:40],
                "due": str(invoice["due"] or ""),
                "usd": self._fin_usd_short(invoice["residual_usd"]),
                "age": FIN_AGING_LABELS[bucket],
                "tones": {"age": ("bad" if bucket == "over90"
                                  else "warn" if bucket in ("b60", "b90")
                                  else "")},
            })
        ar_matrix = self._fin_matrix(
            "fin_ar_open", _("Open customer invoices"), ar_rows,
            [
                {"key": "partner", "label": _("Customer"), "format": "text"},
                {"key": "due", "label": _("Due"), "format": "text"},
                {"key": "usd", "label": _("Outstanding (USD)"),
                 "format": "money"},
                {"key": "age", "label": _("Age"), "format": "text"},
            ],
            _("Sorted by amount; 60 biggest shown — the header link opens "
              "all of them.") + " " + scope_note,
            _("Invoice"), model="account.move",
            domain=[("id", "in", [i["id"] for i in open_invoices])])

        hero = [
            self._fin_kpi(
                "fin_cash", _("Cash in Bank"), cash_total, "usd",
                cash_caption, FIN_BLUE,
                _("Balance of the bank & cash ledgers, converted at "
                  "today's rates. Click for the per-account list.%s")
                % usd_note,
                model="account.move.line",
                modal_table=self._fin_cash_matrix(data, company_id),
                hero=True),
            self._fin_kpi(
                "fin_invoiced", _("Invoiced — %s") % month_label,
                invoiced_month, "usd",
                _("net of credit notes · 13-mo trend"), FIN_BLUE,
                _("Posted customer invoices minus credit notes, by invoice "
                  "date. Click for the month's invoices.%s") % usd_note,
                model="account.move", domain=month_inv_domain,
                points=self._fin_spark_points(
                    spark_months,
                    lambda m: self._fin_invoiced_in(data, keep, m)),
                delta=self._fin_delta(invoiced_month, invoiced_prev),
                hero=True),
            self._fin_kpi(
                "fin_collected", _("Collected — %s") % month_label,
                collected_month, "usd",
                _("money that hit the bank"), FIN_GREEN,
                _("Customer receipts: bank entries matched against "
                  "receivables. Click for the payments received.%s")
                % usd_note,
                model="account.move.line", domain=collected_domain,
                points=self._fin_spark_points(
                    spark_months,
                    lambda m: self._fin_collected_in(data, keep, m)),
                delta=self._fin_delta(collected_month, collected_prev),
                hero=True),
            self._fin_kpi(
                "fin_ar", _("Customers Owe Us"), ar_total, "usd",
                _("avg. wait to get paid ≈ %(days)s days (%(state)s)") % {
                    "days": dso, "state": dso_state},
                FIN_RED if dso > FIN_DSO_WARN else FIN_BLUE,
                _("Unpaid posted invoices. DSO = receivables ÷ last 12 "
                  "months' invoicing × 365. Green up to %(good)s days, red "
                  "beyond %(warn)s. Click for every open invoice.%(note)s")
                % {"good": FIN_DSO_GOOD, "warn": FIN_DSO_WARN,
                   "note": usd_note},
                model="account.move",
                modal_table=ar_matrix,
                scale={"pos": min(100, round(dso / 150 * 100)),
                       "label": _("DSO %(days)s days — %(state)s (green "
                                  "≤%(good)s)") % {
                           "days": dso, "state": dso_state,
                           "good": FIN_DSO_GOOD}},
                hero=True),
        ]

        # ---------------- insights ----------------
        insight_items = self._fin_insight_items(
            data, keep, company_id, today, months_ytd, trend_months,
            scope_note)
        insights = {
            "id": "fin_insights", "name": _("This Week's 3 Things"),
            "type": "insights", "model": "", "mode": "computed",
            "measure": "", "groupby": "", "color": FIN_BLUE,
            "help": _("Read automatically from the books every time the "
                      "page loads — worst first. ") + scope_note,
            "value": float(len(insight_items)), "format": "integer",
            "domain": [], "points": [], "rows": [], "columns": [],
            "span": 12, "error": False, "items": insight_items,
        }

        # ---------------- profit section ----------------
        ladder_values = self._fin_ladder_values(data, keep, months_ytd)
        ladder = self._fin_ladder_widget(
            "fin_ladder", _("P&L Ladder — %s") % window_label, ladder_values,
            _("From revenue down to profit. EBITDA = gross profit + other "
              "income − overheads (interest earned stays in other income; "
              "corporate tax only appears at year-end, as in the books). "
              "Dots: gross ≥%(gp)s%% green, EBITDA ≥%(eb)s%% green. Click "
              "any line for the accounts behind it.%(note)s") % {
                "gp": int(FIN_GP_GOOD), "eb": int(FIN_EBITDA_GOOD),
                "note": usd_note} + " " + scope_note,
            data, keep, months_ytd, scope_note, line_scope)

        monthly_points = []
        monthly_nets = []
        for trend_month in trend_months:
            values = self._fin_ladder_values(data, keep, [trend_month])
            net = values["net"]
            monthly_nets.append(net)
            monthly_points.append({
                "label": self._fin_month_label(trend_month).split(" ")[0],
                "value": abs(round(net)),
                "display": ("+" if net >= 0 else "") + self._fin_usd_short(net),
                "color": FIN_GREEN if net >= 0 else FIN_RED,
                "domain": [], "detail": None,
                "modal_table": self._fin_ladder_matrix(
                    "fin_month_ladder_%s" % trend_month,
                    _("P&L — %s") % self._fin_month_label(trend_month),
                    values, scope_note),
            })
        profit_by_month = {
            "id": "fin_profit_month", "name": _("Profit by Month"),
            "type": "column", "model": "", "mode": "computed",
            "measure": _("Net result (USD)"), "groupby": _("Month"),
            "color": FIN_GREEN,
            "help": _("Green = profit, red = loss. Lumpy is normal in a "
                      "services business. Click a bar for that month's "
                      "ladder.") + " " + scope_note,
            "value": float(round(sum(monthly_nets))),
            "format": "usd", "domain": [], "points": monthly_points,
            "rows": [], "columns": [], "span": 6, "error": False,
            "target": 0.0,
        }

        widgets = [chips] + hero + [
            insights,
            self._fin_sechead("fin_sec_profit",
                              _("Profit — %s") % window_label),
            ladder, profit_by_month,
        ]

        # Profit by company (group view) / tip card (single company)
        if not company_id:
            company_points = []
            seen_labels = {}
            for cid, cname in data["companies"]:
                values = self._fin_ladder_values(
                    data, keep, months_ytd, company_id=cid)
                net = values["net"]
                # OWL keys points by label — duplicate company names
                # (possible: Odoo doesn't enforce uniqueness) would crash
                # the loop, so suffix them like _sales_matrix does.
                label = cname or "?"
                if label in seen_labels:
                    seen_labels[label] += 1
                    label = "%s (%s)" % (label, seen_labels[label])
                else:
                    seen_labels[label] = 1
                company_points.append({
                    "label": label,
                    "value": round(net),
                    "color": FIN_GREEN if net >= 0 else FIN_RED,
                    "domain": [],
                    "modal_table": self._fin_ladder_matrix(
                        "fin_company_ladder_%s" % cid,
                        _("P&L — %s") % cname, values,
                        _("True books incl. intercompany · %s")
                        % window_label),
                })
            company_points.sort(key=lambda p: -p["value"])
            profit_by_company = {
                "id": "fin_profit_company",
                "name": _("Profit by Company — %s") % window_label,
                "type": "bar", "model": "", "mode": "computed",
                "measure": _("Net (USD)"), "groupby": _("Company"),
                "color": FIN_BLUE,
                "help": _("Each company's own books (incl. intercompany — "
                          "SA carries most group partner costs). Click a "
                          "row for that company's ladder."),
                "value": float(len(company_points)), "format": "usd",
                "domain": [], "points": company_points, "rows": [],
                "columns": [], "span": 6, "error": False,
            }
        else:
            profit_by_company = self._fin_kpi(
                "fin_company_tip", _("This Company vs the Group"),
                ladder_values["net"], "usd",
                _("net so far · switch to All companies for side-by-side"),
                FIN_BLUE,
                _("This view is %s's true books, including intercompany. "
                  "The group view strips self-billing.") % company_name,
                span=6)

        combo_points = []
        for combo_month in combo_months:
            combo_points.append({
                "label": self._fin_month_label(combo_month),
                "bar": round(self._fin_invoiced_in(data, keep, combo_month)),
                "line": round(self._fin_collected_in(data, keep,
                                                     combo_month)),
                "domain": [],
            })
        invoiced_vs_collected = {
            "id": "fin_inv_vs_col",
            "name": _("Invoiced vs Collected — last 6 months"),
            "type": "combo", "model": "", "mode": "computed",
            "measure": _("USD"), "groupby": _("Month"), "color": FIN_BLUE,
            "help": _("Bars = what we billed. Line = what actually arrived "
                      "in the bank. Bars beating the line month after month "
                      "= the owed pile grows.") + " " + scope_note,
            "value": float(sum(p["bar"] for p in combo_points)),
            "format": "usd", "domain": [], "points": combo_points,
            "rows": [], "columns": [], "span": 6, "error": False,
            "label_line": _("Collected"), "label_bar": _("Invoiced"),
        }

        widgets += [profit_by_company, invoiced_vs_collected]

        # ---------------- getting paid ----------------
        buckets = {b: 0.0 for b in FIN_AGING_BUCKETS}
        bucket_ids = {b: [] for b in FIN_AGING_BUCKETS}
        for invoice in open_invoices:
            days = (today - fields.Date.to_date(str(invoice["due"]))).days \
                if invoice["due"] else 0
            bucket = self._fin_aging_bucket(days)
            buckets[bucket] += invoice["residual_usd"]
            bucket_ids[bucket].append(invoice["id"])
        aging_points = [{
            "label": FIN_AGING_LABELS[bucket],
            "value": round(buckets[bucket]),
            "color": FIN_AGING_COLORS[bucket],
            "domain": self._json_safe([("id", "in", bucket_ids[bucket])]),
            "detail": None,
        } for bucket in FIN_AGING_BUCKETS]
        aging = {
            "id": "fin_aging", "name": _("How Late Is the Money We're Owed?"),
            "type": "column", "model": "account.move", "mode": "computed",
            "measure": _("Outstanding (USD)"), "groupby": _("Age"),
            "color": FIN_RED,
            "help": _("Open customer invoices by how overdue they are "
                      "(due date + today). Click a bar for its invoices.")
            + " " + scope_note,
            "value": float(round(ar_total)), "format": "usd",
            "domain": self._json_safe(
                [("id", "in", [i["id"] for i in open_invoices])]),
            "points": aging_points, "rows": [], "columns": [], "span": 6,
            "error": False, "target": 0.0,
        }

        debtors = {}
        for invoice in open_invoices:
            if invoice["ic"]:
                continue
            entry = debtors.setdefault(
                invoice["partner"], {"usd": 0.0, "ids": []})
            entry["usd"] += invoice["residual_usd"]
            entry["ids"].append(invoice["id"])
        chase_entries = sorted(debtors.items(), key=lambda kv: -kv[1]["usd"])[:7]
        chase_max = chase_entries[0][1]["usd"] if chase_entries else 1.0
        chase_points = [{
            "label": partner,
            "value": round(entry["usd"]),
            "color": (FIN_RED if entry["usd"] > chase_max * FIN_CHASE_RED_SHARE
                      else "#d97706" if entry["usd"] > chase_max
                      * FIN_CHASE_AMBER_SHARE else FIN_BLUE),
            "domain": self._json_safe([("id", "in", entry["ids"])]),
        } for partner, entry in chase_entries]
        chase = {
            "id": "fin_chase", "name": _("Who Should We Chase First?"),
            "type": "bar", "model": "account.move", "mode": "computed",
            "measure": _("Outstanding (USD)"), "groupby": _("Customer"),
            "color": FIN_BLUE,
            "help": _("Top outside debtors by open amount — intercompany "
                      "never appears here (it has its own housekeeping "
                      "line). Click a row for their invoices."),
            "value": float(len(chase_points)), "format": "usd",
            "domain": [], "points": chase_points, "rows": [], "columns": [],
            "span": 6, "error": False,
        }

        widgets += [self._fin_sechead("fin_sec_paid", _("Getting paid")),
                    aging, chase]

        # ---------------- customers & spend ----------------
        conc_set = set(conc_months)
        revenue_by_partner = {}
        for invoice in data["invoices"]:
            if invoice["month"] not in conc_set or not keep(invoice):
                continue
            entry = revenue_by_partner.setdefault(
                invoice["partner"], {"usd": 0.0, "ids": []})
            entry["usd"] += invoice["usd"]
            entry["ids"].append(invoice["id"])
        ranked = sorted(
            ((p, e) for p, e in revenue_by_partner.items() if e["usd"] > 0),
            key=lambda kv: -kv[1]["usd"])
        conc_total = sum(e["usd"] for _p, e in ranked) or 1.0
        top3 = ranked[:3]
        top3_share = sum(e["usd"] for _p, e in top3) / conc_total * 100.0
        donut_points = [{
            "label": partner,
            "value": round(entry["usd"] / conc_total * 100.0, 1),
            "domain": self._json_safe([("id", "in", entry["ids"])]),
        } for partner, entry in top3]
        rest = 100.0 - sum(p["value"] for p in donut_points)
        donut_points.append({"label": _("Everyone else"),
                             "value": round(max(rest, 0.0), 1),
                             "domain": []})
        conc_rows = [{
            "label": partner,
            "domain": self._json_safe([("id", "in", entry["ids"])]),
            "usd": self._fin_usd_short(entry["usd"]),
            "share": self._ops_pct_text(entry["usd"] / conc_total * 100.0),
            "tones": {"share": "warn" if index < 3 else ""},
        } for index, (partner, entry) in enumerate(ranked[:10])]
        donut = {
            "id": "fin_concentration", "name": _("Customer Concentration"),
            "type": "donut", "model": "account.move", "mode": "computed",
            "measure": _("share of 12-mo invoicing"), "groupby": _("Customer"),
            "color": FIN_BLUE,
            "help": _("Top 3 customers' share of the last 12 months' "
                      "invoicing — how big a hole the biggest customer "
                      "would leave. Click for the top-10 table.")
            + " " + scope_note,
            "value": round(top3_share, 1), "format": "percent",
            "domain": [], "points": donut_points, "rows": [], "columns": [],
            "span": 6, "error": False,
            "modal_table": self._fin_matrix(
                "fin_concentration_table",
                _("Revenue by Customer — last 12 months"), conc_rows,
                [
                    {"key": "usd", "label": _("Invoiced (USD)"),
                     "format": "money"},
                    {"key": "share", "label": _("Share"), "format": "money"},
                ],
                _("Net invoiced over the trailing 12 months; the top 3 "
                  "(highlighted) drive the concentration number."),
                _("Customer"), model="account.move"),
        }

        ytd_set = set(months_ytd)
        spend = {}
        spend_accounts = {}
        spend_by_month = {}
        for row in data["pl"]:
            if row["bucket"] not in ("dc", "opex", "da"):
                continue
            if row["month"] not in ytd_set or not keep(row):
                continue
            spend[row["account"]] = spend.get(row["account"], 0.0) + row["usd"]
            spend_accounts.setdefault(row["account"], set()).add(
                row["account_id"])
            month_key = (row["account"], row["month"])
            spend_by_month[month_key] = spend_by_month.get(month_key, 0.0) \
                + row["usd"]
        top_spend = sorted(spend.items(), key=lambda kv: -abs(kv[1]))[:6]
        ytd_start = "%s-01" % months_ytd[0]
        _unused, ytd_end = self._fin_month_bounds(months_ytd[-1])
        spend_points = []
        for account, value in top_spend:
            month_rows = []
            for spend_month in months_ytd:
                month_total = spend_by_month.get((account, spend_month), 0.0)
                m_start, m_end = self._fin_month_bounds(spend_month)
                month_rows.append({
                    "label": self._fin_month_label(spend_month),
                    "domain": self._json_safe([
                        ("account_id", "in",
                         sorted(spend_accounts[account])),
                        ("parent_state", "=", "posted"),
                        ("date", ">=", str(m_start)),
                        ("date", "<=", str(m_end))] + line_scope),
                    "usd": self._fin_usd_short(month_total),
                    "tones": {},
                })
            spend_points.append({
                "label": account,
                "value": round(abs(value)),
                "color": FIN_BLUE,
                "domain": self._json_safe([
                    ("account_id", "in", sorted(spend_accounts[account])),
                    ("parent_state", "=", "posted"),
                    ("date", ">=", ytd_start), ("date", "<=", str(ytd_end))]
                    + line_scope),
                "modal_table": self._fin_matrix(
                    "fin_spend_%s" % re.sub(r"\W+", "_", account.lower()),
                    _("%s — month by month") % account, month_rows,
                    [{"key": "usd", "label": _("USD"), "format": "money"}],
                    scope_note, _("Month"), model="account.move.line"),
            })
        spend_widget = {
            "id": "fin_spend", "name": _("Where the Money Goes — %s")
            % window_label,
            "type": "bar", "model": "account.move.line", "mode": "computed",
            "measure": _("Spend (USD)"), "groupby": _("Category"),
            "color": FIN_BLUE,
            "help": _("Top spending categories from the expense ledgers "
                      "(same-named accounts merged across companies). "
                      "Click a row for the month-by-month detail.")
            + " " + scope_note,
            "value": float(len(spend_points)), "format": "usd",
            "domain": [], "points": spend_points, "rows": [], "columns": [],
            "span": 6, "error": False,
        }

        widgets += [self._fin_sechead("fin_sec_spend",
                                      _("Customers & spend")),
                    donut, spend_widget]

        # ---------------- AP & housekeeping ----------------
        ap_rows_src = [b for b in data["ap_bills"] if keep(b)]
        ap_total = sum(b["usd"] for b in ap_rows_src)
        bill_rows = [{
            "label": bill["name"],
            "domain": self._json_safe([("id", "=", bill["id"])]),
            "partner": bill["partner"][:40],
            "date": str(bill["date"] or ""),
            "usd": self._fin_usd_short(bill["usd"]),
            "tones": {},
        } for bill in sorted(ap_rows_src, key=lambda b: -b["usd"])[:40]]
        bills_matrix = self._fin_matrix(
            "fin_ap_bills", _("Open supplier bills"), bill_rows,
            [
                {"key": "partner", "label": _("Supplier"), "format": "text"},
                {"key": "date", "label": _("Bill date"), "format": "text"},
                {"key": "usd", "label": _("To pay (USD)"), "format": "money"},
            ],
            scope_note, _("Bill"), model="account.move",
            domain=[("id", "in", [b["id"] for b in ap_rows_src])])

        ic_open = [i for i in self._fin_open_invoices(data, lambda r: True)
                   if i["ic"]]
        ic_ar_total = sum(i["residual_usd"] for i in ic_open)
        ic_rows = [{
            "label": invoice["name"],
            "domain": self._json_safe([("id", "=", invoice["id"])]),
            "partner": invoice["partner"][:40],
            "usd": self._fin_usd_short(invoice["residual_usd"]),
            "tones": {},
        } for invoice in sorted(ic_open, key=lambda i: -i["residual_usd"])]
        ic_matrix = self._fin_matrix(
            "fin_ic_ar", _("Intercompany receivables"), ic_rows,
            [
                {"key": "partner", "label": _("Billed to"), "format": "text"},
                {"key": "usd", "label": _("Outstanding (USD)"),
                 "format": "money"},
            ],
            _("Money the group owes itself — excluded from group KPIs."),
            _("Invoice"), model="account.move",
            domain=[("id", "in", [i["id"] for i in ic_open])])

        hyg = data["hyg"]
        # Housekeeping counts come from company-filtered data — their
        # click-throughs must scope the same way (IC stays in: the counts
        # include it in both views).
        hk_scope = [("company_id", "=", company_id)] if company_id else []
        housekeeping_rows = [
            {
                "label": _("Open supplier bills (AP)"),
                "domain": [],
                "val": self._fin_usd_short(ap_total),
                "status": _("click for the list"),
                "tones": {},
                "modal_table": bills_matrix,
            },
            {
                "label": _("Invoices without payment terms"),
                "model": "account.move",
                "domain": self._json_safe([
                    ("move_type", "in", ["out_invoice", "out_refund"]),
                    ("state", "=", "posted"),
                    ("invoice_payment_term_id", "=", False)] + hk_scope),
                "val": _("%(n)s of %(total)s") % {
                    "n": hyg["no_terms"], "total": hyg["inv_total"]},
                "status": _("tidy up") if hyg["no_terms"] else _("clean"),
                "tones": {"status": "warn" if hyg["no_terms"] else "good"},
            },
            {
                "label": _("Bank lines not yet reconciled"),
                "model": "account.bank.statement.line",
                "domain": self._json_safe(
                    [("is_reconciled", "=", False)] + hk_scope),
                "val": "%s" % hyg["unrec"],
                "status": _("healthy") if hyg["unrec"] < 60 else _("catch up"),
                "tones": {"status": "good" if hyg["unrec"] < 60 else "warn"},
            },
            {
                "label": _("Intercompany owed (kept out of group KPIs)"),
                "domain": [],
                "val": self._fin_usd_short(ic_ar_total),
                "status": _("visible"),
                "tones": {"status": "warn"},
                "modal_table": ic_matrix,
            },
            {
                "label": _("Account names to clean (\"(copy)\")"),
                "model": "account.account",
                "domain": self._json_safe([("name", "like", "(copy)")]),
                "val": "%s" % hyg["copy_accounts"],
                "status": _("tidy up") if hyg["copy_accounts"] else _("clean"),
                "tones": {"status": "warn" if hyg["copy_accounts"]
                          else "good"},
            },
        ]
        housekeeping = self._fin_matrix(
            "fin_housekeeping", _("Bills to Pay & Housekeeping"),
            housekeeping_rows,
            [
                {"key": "val", "label": _("Today"), "format": "money"},
                {"key": "status", "label": _("Status"), "format": "text"},
            ],
            _("What we owe soon, and whether the bookkeeping is staying "
              "clean. Every row clicks through.") + " " + scope_note,
            _("Check"), span=12)

        widgets.append(housekeeping)
        return widgets
