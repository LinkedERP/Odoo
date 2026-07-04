from datetime import timedelta

from odoo import api, fields, models, _

SLA_DASHBOARD_NAME = "Weekly Support & SLA Dashboard"

# Fiscal month rule (Akshay 2026-07-04, ALL customers & companies):
# a day up to the 25th belongs to its calendar month's fiscal month;
# the 26th onward belongs to the NEXT month's fiscal month.
FISCAL_CUT_DAY = 25

# Ticket tag buckets. Performance Management is excluded EVERYWHERE.
TAG_CR = "change request"
TAG_PM = "performance management"

SLA_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PROJECT_NATURE_FIELD = "x_studio_nature"
STATUS_N_FIELD = "x_studio_statusn"
INVOICE_DUE_DAYS = 30


class LinkederpDashboardSla(models.Model):
    _inherit = "linkederp.dashboard"

    # ------------------------------------------------------------------
    # Packaging / detection
    # ------------------------------------------------------------------
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        self._ensure_sla_dashboard()

    def _ensure_sla_dashboard(self):
        if self._ensure_dashboard_name(SLA_DASHBOARD_NAME, []):
            return
        if "helpdesk.ticket" not in self.env:
            return
        self.create(
            {
                "name": SLA_DASHBOARD_NAME,
                "sequence": 65,
                "bucket": "management",
                "description": _(
                    "Customer-facing weekly support report: tickets, SLA "
                    "hours vs the contract allowance (fiscal months, 26th "
                    "to 25th), billed hours and open invoices. Export as "
                    "PDF to send to the customer."
                ),
                "color": "#1e5b96",
            }
        )

    def _is_sla_dashboard(self):
        self.ensure_one()
        return (self.name or "").strip().lower() == SLA_DASHBOARD_NAME.lower()

    # ------------------------------------------------------------------
    # Fiscal-month helpers (26th -> 25th)
    # ------------------------------------------------------------------
    @api.model
    def _sla_fiscal_key(self, day):
        """(year, month) fiscal bucket the date belongs to."""
        if day.day > FISCAL_CUT_DAY:
            nxt = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
            return (nxt.year, nxt.month)
        return (day.year, day.month)

    @api.model
    def _sla_fiscal_window(self, today):
        """(start, end) of today's fiscal month: 26th -> 25th."""
        if today.day > FISCAL_CUT_DAY:
            start = today.replace(day=26)
        else:
            prev = today.replace(day=1) - timedelta(days=1)
            start = prev.replace(day=26)
        end = (start + timedelta(days=32)).replace(day=FISCAL_CUT_DAY)
        return start, end

    @api.model
    def _sla_fiscal_label(self, key):
        return "%s %02d" % (SLA_MONTH_LABELS[key[1] - 1], key[0] % 100)

    # ------------------------------------------------------------------
    # Customer & contract resolution
    # ------------------------------------------------------------------
    def _sla_support_projects(self):
        Project = self.env["project.project"]
        if PROJECT_NATURE_FIELD not in Project._fields:
            return Project.browse()
        return Project.with_context(active_test=False).search(
            [(PROJECT_NATURE_FIELD, "=", "Support"), ("partner_id", "!=", False)])

    def _sla_customer_options(self):
        customers = {}
        for project in self._sla_support_projects():
            partner = project.partner_id.commercial_partner_id
            if partner:
                customers[partner.id] = partner.name
        return [{"id": pid, "name": name}
                for pid, name in sorted(customers.items(), key=lambda kv: kv[1])]

    def _sla_selected_customer(self, filters=False):
        filters = filters or {}
        options = {o["id"] for o in self._sla_customer_options()}
        try:
            value = int(filters.get("sla_customer_id") or 0)
        except (TypeError, ValueError):
            value = 0
        if value in options:
            return value
        ordered = self._sla_customer_options()
        return ordered[0]["id"] if ordered else False

    def _sla_filter_options(self, filters=False):
        return {
            "enabled": True,
            "customer": self._sla_selected_customer(filters) or "",
            "customers": self._sla_customer_options(),
        }

    def _sla_contract(self, customer_id, today):
        """The customer's Support project covering today (else the latest):
        (project, start, end, sale_order)."""
        projects = self._sla_support_projects().filtered(
            lambda p: p.partner_id.commercial_partner_id.id == customer_id)
        if not projects:
            return None
        covering = projects.filtered(
            lambda p: p.date_start and p.date
            and p.date_start <= today <= p.date)
        pick = covering or projects.sorted(
            key=lambda p: p.date_start or fields.Date.to_date("1900-01-01"),
            reverse=True)
        project = pick[0]
        return (project, project.date_start, project.date, project.sale_order_id)

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------
    def _sla_ticket_bucket(self, ticket, tag_names):
        names = [tag_names.get(tag_id, "") for tag_id in ticket.tag_ids.ids]
        if any(TAG_CR in name for name in names):
            return "CR"
        if any(TAG_PM in name for name in names):
            return "PM"
        return "SLA"

    def _sla_collect(self, customer_id, today):
        Ticket = self.env["helpdesk.ticket"].with_context(active_test=False)
        tag_names = {tag.id: (tag.name or "").lower()
                     for tag in self.env["helpdesk.tag"].search([])}
        contract = self._sla_contract(customer_id, today)
        c_start = contract[1] if contract else False
        c_end = contract[2] if contract else False
        order = contract[3] if contract else False

        tickets = []
        has_hours = "total_hours_spent" in Ticket._fields
        for ticket in Ticket.search(
                [("commercial_partner_id", "=", customer_id)]):
            bucket = self._sla_ticket_bucket(ticket, tag_names)
            if bucket == "PM":
                continue
            created = ticket.create_date and ticket.create_date.date()
            closed = ticket.close_date and ticket.close_date.date()
            stage = (ticket.stage_id.name or "")
            status = ticket[STATUS_N_FIELD] if STATUS_N_FIELD in Ticket._fields else False
            tickets.append({
                "id": ticket.id,
                "ref": ticket.ticket_ref or str(ticket.id),
                "name": ticket.name or "?",
                "owner": ticket.user_id.name or _("Unassigned"),
                "created": created, "closed": closed,
                "active": ticket.active,
                "stage": stage,
                "on_hold": "hold" in stage.lower(),
                "status": status,
                "bucket": bucket,
                "hours": ticket.total_hours_spent if has_hours else 0.0,
                "carryover": bool(c_start and created and created < c_start),
            })

        # billable hours on those tickets, bucketed later as needed
        lines = []
        Line = self.env["account.analytic.line"]
        if "helpdesk_ticket_id" in Line._fields and tickets:
            bucket_by_id = {t["id"]: t["bucket"] for t in tickets}
            for line in Line.search(
                    [("helpdesk_ticket_id", "in", [t["id"] for t in tickets]),
                     ("timesheet_invoice_type", "!=", "non_billable")]):
                lines.append({
                    "date": line.date,
                    "hours": line.unit_amount or 0.0,
                    "bucket": bucket_by_id.get(line.helpdesk_ticket_id.id, "SLA"),
                })

        # posted customer invoices of the SLA sale order
        invoices = []
        if order:
            for move in order.invoice_ids:
                if move.move_type != "out_invoice" or move.state != "posted":
                    continue
                billed = 0.0
                for mline in move.invoice_line_ids:
                    uom = (mline.product_uom_id.name or "").lower()
                    if "hour" in uom:
                        billed += mline.quantity
                inv_date = move.invoice_date
                due = inv_date + timedelta(days=INVOICE_DUE_DAYS) if inv_date else False
                open_inv = move.payment_state not in ("paid", "in_payment", "reversed")
                invoices.append({
                    "id": move.id, "name": move.name,
                    "date": inv_date, "due": due,
                    "currency": move.currency_id.name or "",
                    "amount": move.amount_total,
                    "currency_rec": move.currency_id,
                    "open": open_inv,
                    "overdue": bool(open_inv and due and due < today),
                    "billed_hours": billed,
                })
        return {
            "contract": contract, "start": c_start, "end": c_end,
            "order": order, "tickets": tickets, "lines": lines,
            "invoices": invoices,
        }

    # ------------------------------------------------------------------
    # Report values (shared by the dashboard payload AND the PDF)
    # ------------------------------------------------------------------
    def _sla_report_values(self, customer_id):
        today = fields.Date.context_today(self)
        data = self._sla_collect(customer_id, today)
        tickets, lines = data["tickets"], data["lines"]
        c_start, c_end = data["start"], data["end"]
        allowance = data["order"].sla_monthly_hours if data["order"] and \
            "sla_monthly_hours" in data["order"]._fields else 0.0

        # weeks: last 4 completed Mon-Sun weeks
        this_monday = today - timedelta(days=today.weekday())
        mondays = [this_monday - timedelta(weeks=i) for i in (4, 3, 2, 1)]
        weeks = []
        for monday in mondays:
            sunday = monday + timedelta(days=6)
            weeks.append({
                "monday": monday,
                "label": _("W %s") % monday.strftime("%d %b"),
                "created": [t for t in tickets
                            if t["created"] and monday <= t["created"] <= sunday],
                "closed": [t for t in tickets
                           if t["closed"] and monday <= t["closed"] <= sunday],
                "sla_hours": sum(l["hours"] for l in lines
                                 if l["bucket"] == "SLA" and monday <= l["date"] <= sunday),
                "cr_hours": sum(l["hours"] for l in lines
                                if l["bucket"] == "CR" and monday <= l["date"] <= sunday),
            })

        created_ctd = [t for t in tickets if c_start and t["created"]
                       and c_start <= t["created"] <= today]
        closed_ctd = [t for t in tickets if c_start and t["closed"]
                      and c_start <= t["closed"] <= today]
        # Archived/merged tickets often keep no close date — they are not
        # "open" on a customer report.
        open_now = [t for t in tickets if not t["closed"] and t["active"]]
        on_hold = [t for t in open_now if t["on_hold"]]
        carryovers = [t for t in open_now if t["carryover"]]

        f_start, f_end = self._sla_fiscal_window(today)
        f_key = self._sla_fiscal_key(today)
        mtd_sla = sum(l["hours"] for l in lines
                      if l["bucket"] == "SLA"
                      and self._sla_fiscal_key(l["date"]) == f_key)
        mtd_cr = sum(l["hours"] for l in lines
                     if l["bucket"] == "CR"
                     and self._sla_fiscal_key(l["date"]) == f_key)
        pct_used = mtd_sla / allowance * 100.0 if allowance else 0.0

        # Contract fiscal months + billed hours per fiscal month. The loop
        # runs over FISCAL keys (26th->25th windows), so a contract aligned
        # to the fiscal cut (e.g. 26 Jun -> 25 Jun) gets no spurious leading
        # bar and an invoice dated after the 25th of the last month is not
        # dropped.
        months = []
        if c_start and c_end:
            key = self._sla_fiscal_key(c_start)
            end_key = self._sla_fiscal_key(c_end)
            while key <= end_key:
                billed = sum(inv["billed_hours"] for inv in data["invoices"]
                             if inv["date"]
                             and self._sla_fiscal_key(inv["date"]) == key)
                invoice_ids = [inv["id"] for inv in data["invoices"]
                               if inv["date"]
                               and self._sla_fiscal_key(inv["date"]) == key]
                months.append({"key": key,
                               "label": self._sla_fiscal_label(key),
                               "billed": billed,
                               "invoice_ids": invoice_ids})
                key = ((key[0] + 1, 1) if key[1] == 12
                       else (key[0], key[1] + 1))

        tenure_pct = 0.0
        if c_start and c_end and c_end > c_start:
            tenure_pct = max(0.0, min(100.0, (today - c_start).days
                                      / (c_end - c_start).days * 100.0))

        return {
            "today": today, "customer_id": customer_id,
            "customer_name": self.env["res.partner"].browse(customer_id).name
            if customer_id else "",
            "contract_start": c_start, "contract_end": c_end,
            "order": data["order"],
            "allowance": allowance,
            "week_label": _("%(a)s – %(b)s") % {
                "a": mondays[-1].strftime("%d %b"),
                "b": (mondays[-1] + timedelta(days=6)).strftime("%d %b %Y")},
            "fiscal_label": _("26 %(a)s – 25 %(b)s") % {
                "a": SLA_MONTH_LABELS[f_start.month - 1],
                "b": SLA_MONTH_LABELS[f_end.month - 1]},
            "weeks": weeks,
            "created_ctd": created_ctd, "closed_ctd": closed_ctd,
            "open_now": open_now, "on_hold": on_hold,
            "carryovers": carryovers,
            "mtd_sla": mtd_sla, "mtd_cr": mtd_cr, "pct_used": pct_used,
            "months": months, "invoices": data["invoices"],
            "tenure_pct": tenure_pct,
        }

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------
    def _sla_kpi(self, wid, name, value, fmt, caption, color, help_text,
                 domain=None, span=2):
        return {
            "id": wid, "name": name, "type": "kpi",
            "model": "helpdesk.ticket", "mode": "computed",
            "measure": caption, "groupby": "", "color": color,
            "help": help_text, "value": float(value), "format": fmt,
            "domain": self._json_safe(domain or []),
            "points": [], "rows": [], "columns": [],
            "span": span, "error": False, "modal_table": False,
        }

    def _sla_gauge(self, wid, name, value, caption, color, help_text, span=2):
        widget = self._sla_kpi(wid, name, value, "percent", caption, color,
                               help_text, span=span)
        widget["type"] = "gauge"
        # Pure percentage tiles: no record list makes sense behind them.
        widget["model"] = ""
        return widget

    def _sla_delta_caption(self, weeks, key):
        this_week = len(weeks[-1][key])
        prior = len(weeks[-2][key]) if len(weeks) > 1 else 0
        delta = this_week - prior
        arrow = "▲" if delta > 0 else "▼" if delta < 0 else "•"
        return _("%(arrow)s %(delta)s vs prior week") % {
            "arrow": arrow, "delta": abs(delta)}

    def _sla_dashboard_widgets(self, date_from=False, date_to=False,
                               filters=False):
        customer_id = self._sla_selected_customer(filters)
        if not customer_id or "helpdesk.ticket" not in self.env:
            return [self._sla_kpi(
                "sla_empty", _("Weekly Support & SLA Dashboard"), 0, "integer",
                _("No customer with a Support-nature project found."),
                "#64748b", _("Tag support projects with Nature = Support to "
                             "populate the customer list."), span=12)]
        values = self._sla_report_values(customer_id)
        weeks = values["weeks"]
        allowance = values["allowance"]

        chips = {
            "id": "sla_header", "name": _("Context"), "type": "chips",
            "model": "", "mode": "computed", "measure": "", "groupby": "",
            "color": "#1e5b96", "help": "", "value": 0.0, "format": "integer",
            "domain": [], "points": [], "rows": [], "columns": [],
            "span": 12, "error": False,
            "chips": [
                {"icon": "fa-building", "tone": "accent",
                 "text": _("Customer: %s") % values["customer_name"]},
                {"icon": "fa-calendar", "tone": "",
                 "text": _("Week: %s") % values["week_label"]},
                {"icon": "fa-file-text-o", "tone": "",
                 "text": _("Contract: %(a)s – %(b)s") % {
                     "a": self._ops_date_text(values["contract_start"]),
                     "b": self._ops_date_text(values["contract_end"])}},
                {"icon": "fa-clock-o", "tone": "",
                 "text": _("Fiscal month: %s") % values["fiscal_label"]},
            ],
        }

        open_ids = [t["id"] for t in values["open_now"]]
        all_ticket_ids = ([t["id"] for t in values["created_ctd"]]
                          + [t["id"] for t in values["open_now"]])
        pct = values["pct_used"]
        gauge_color = ("#dc2626" if pct >= 95 else
                       "#d97706" if pct >= 75 else "#059669")
        allowance_caption = (
            _("%(rem)s h remaining of %(all)s") % {
                "rem": self._ops_short_hours(max(allowance - values["mtd_sla"], 0.0)),
                "all": self._ops_short_hours(allowance)}
            if allowance else _("allowance not set on the SO ⚠"))

        widgets = [
            chips,
            self._sla_kpi(
                "sla_created", _("Total Tickets Created"),
                len(values["created_ctd"]), "integer",
                self._sla_delta_caption(weeks, "created"),
                "#2563eb",
                _("Tickets created since the contract start (%s). "
                  "Performance-Management-tagged tickets are excluded "
                  "everywhere.") % self._ops_date_text(values["contract_start"]),
                domain=[("id", "in", [t["id"] for t in values["created_ctd"]])]),
            self._sla_kpi(
                "sla_closed", _("Total Tickets Closed"),
                len(values["closed_ctd"]), "integer",
                self._sla_delta_caption(weeks, "closed"),
                "#059669",
                _("Tickets closed since the contract start."),
                domain=[("id", "in", [t["id"] for t in values["closed_ctd"]])]),
            self._sla_kpi(
                "sla_open", _("Tickets Open"),
                len(values["open_now"]), "integer",
                _("%(active)s Active & %(hold)s On Hold · %(carry)s carried over") % {
                    "active": len(values["open_now"]) - len(values["on_hold"]),
                    "hold": len(values["on_hold"]),
                    "carry": len(values["carryovers"])},
                "#7c3aed",
                _("All currently open tickets regardless of age — tickets "
                  "created under a previous contract are counted and badged "
                  "as carried over."),
                domain=[("id", "in", open_ids)]),
            self._sla_kpi(
                "sla_hours_mtd", _("SLA Hours Used (fiscal mth)"),
                round(values["mtd_sla"], 2), "number",
                _("CR hours used: %s") % self._ops_short_hours(values["mtd_cr"]),
                "#1e5b96",
                _("Billable hours logged on this customer's tickets in the "
                  "current fiscal month (%s). SLA = non-Change-request, "
                  "non-Performance-Management; CR shown separately.")
                % values["fiscal_label"],
                domain=[("id", "in", all_ticket_ids)]),
            self._sla_gauge(
                "sla_monthly_pct", _("Monthly SLA hrs used"),
                round(min(pct, 100.0), 1), allowance_caption, gauge_color,
                _("Fiscal-month consumption vs the Monthly SLA Hours "
                  "Allowance on the contract's sale order.")
                + (_(" Currently %(pct)s%% of %(all)s h.") % {
                    "pct": round(pct, 1),
                    "all": self._ops_short_hours(allowance)} if allowance else "")),
            self._sla_gauge(
                "sla_tenure", _("Tenure Elapsed"),
                round(values["tenure_pct"], 1),
                _("⌛ expires %s") % self._ops_date_text(values["contract_end"]),
                "#1e5b96",
                _("Share of the contract period already elapsed (as of "
                  "today).")),
            self._sla_weekly_tickets(weeks),
            self._sla_weekly_hours(weeks),
            self._sla_open_table(values),
            self._sla_billed_column(values),
            self._sla_invoice_table(values),
        ]
        return widgets

    def _sla_weekly_tickets(self, weeks):
        points = [{
            "label": week["label"],
            "a": len(week["created"]),
            "b": len(week["closed"]),
            "domain": self._json_safe(
                [("id", "in", [t["id"] for t in week["created"]])]),
            "domain_b": self._json_safe(
                [("id", "in", [t["id"] for t in week["closed"]])]),
        } for week in weeks]
        week_ticket_ids = sorted({t["id"] for week in weeks
                                  for t in week["created"] + week["closed"]})
        return {
            "id": "sla_weekly_tickets",
            "name": _("Tickets created & closed — last 4 weeks"),
            "type": "columns2", "model": "helpdesk.ticket",
            "mode": "computed", "measure": _("Tickets"), "groupby": _("Week"),
            "color": "#b03030", "help": _(
                "Completed Monday-Sunday weeks. Red = created, green = "
                "closed; click a bar for the tickets."),
            "value": float(sum(p["a"] for p in points)), "format": "integer",
            "domain": self._json_safe([("id", "in", week_ticket_ids)]),
            "points": points, "rows": [], "columns": [],
            "span": 6, "error": False,
            "label_a": _("Created"), "label_b": _("Closed"),
        }

    def _sla_weekly_hours(self, weeks):
        points = [{
            "label": week["label"],
            "line": round(week["sla_hours"], 2),
            "bar": round(week["cr_hours"], 2),
            "domain": [],
        } for week in weeks]
        return {
            "id": "sla_weekly_hours",
            "name": _("Hours consumed — last 4 weeks"),
            "type": "combo", "model": "",
            "mode": "computed", "measure": _("Hours"), "groupby": _("Week"),
            "color": "#1e5b96", "help": _(
                "Line = SLA hours (billable, non-CR, non-PM); bars = "
                "Change-request hours. Completed weeks."),
            "value": float(sum(p["line"] for p in points)), "format": "number",
            "domain": [], "points": points, "rows": [], "columns": [],
            "span": 6, "error": False,
            "label_line": _("SLA hours"), "label_bar": _("CR hours"),
        }

    def _sla_open_table(self, values):
        # NB: _sales_matrix hardcodes model crm.lead — override below so row
        # clicks open the helpdesk ticket, not an unrelated lead.
        rows = []
        for ticket in sorted(values["open_now"], key=lambda t: t["created"] or fields.Date.today()):
            status = ticket["status"] or _("%s *") % (ticket["stage"] or "?")
            created_text = self._ops_date_text(ticket["created"])
            rows.append({
                "label": ticket["ref"],
                "sub": ticket["name"][:70],
                "domain": self._json_safe([("id", "=", ticket["id"])]),
                "tag": _("Change request") if ticket["bucket"] == "CR"
                else _("service Request"),
                "created": (created_text + _(" · carried over")
                            if ticket["carryover"] else created_text),
                "owner": ticket["owner"],
                "status": status,
                "hours": self._ops_short_hours(ticket["hours"]),
                "tones": {"created": "warn" if ticket["carryover"] else "",
                          "status": "" if ticket["status"] else "warn"},
            })
        widget = self._sales_matrix(
            "sla_open_tickets", _("Open Tickets Details"), rows,
            [
                {"key": "tag", "label": _("Tags"), "format": "text"},
                {"key": "created", "label": _("Created on"), "format": "text"},
                {"key": "owner", "label": _("Owner"), "format": "text"},
                {"key": "status", "label": _("Ticket Status"), "format": "text"},
                {"key": "hours", "label": _("Total Time Spent"), "format": "money"},
            ],
            _("Ticket Status comes from the Status(N) field; “*” = not set, "
              "showing the helpdesk stage instead. “Carried over” = created "
              "under a previous contract and still open."),
            _("ID"), span=12, color="#1e5b96")
        widget["model"] = "helpdesk.ticket"
        widget["domain"] = self._json_safe(
            [("id", "in", [t["id"] for t in values["open_now"]])])
        return widget

    def _sla_billed_column(self, values):
        points = []
        for month in values["months"]:
            points.append({
                "label": month["label"],
                "value": round(month["billed"], 1),
                "color": ("#d97706" if values["allowance"]
                          and month["billed"] > values["allowance"]
                          else "#1e5b96"),
                "domain": self._json_safe(
                    [("id", "in", month.get("invoice_ids", []))]),
                "detail": None,
            })
        return {
            "id": "sla_billed_monthly",
            "name": _("Monthly SLA Hours — billed on invoices"),
            "type": "column", "model": "account.move",
            "mode": "computed", "measure": _("Hours billed"),
            "groupby": _("Fiscal month"), "color": "#1e5b96",
            "help": _(
                "Hours invoiced per fiscal month (invoice lines with an "
                "hour-based unit, bucketed by the invoice date's fiscal "
                "month). Fixed-fee invoices bill 0 hours. Dashed line = "
                "the monthly allowance."),
            "value": float(sum(p["value"] for p in points)),
            "format": "number", "domain": [], "points": points,
            "rows": [], "columns": [], "span": 5, "error": False,
            "target": float(values["allowance"] or 0.0),
        }

    def _sla_invoice_table(self, values):
        rows = []
        for inv in values["invoices"]:
            if not inv["open"]:
                continue
            rows.append({
                "label": inv["name"],
                "domain": self._json_safe([("id", "=", inv["id"])]),
                "date": self._ops_date_text(inv["date"]),
                "due": self._ops_date_text(inv["due"]),
                "ccy": inv["currency"],
                "amount": self._ops_money(inv["amount"], inv["currency_rec"]),
                "status": _("⚠ Overdue") if inv["overdue"] else _("✓ On Time"),
                "tones": {"status": "bad" if inv["overdue"] else "good"},
            })
        widget = self._sales_matrix(
            "sla_open_invoices", _("Open SLA Invoices Details"), rows,
            [
                {"key": "date", "label": _("Invoice Date"), "format": "text"},
                {"key": "due", "label": _("Due Date (+30d)"), "format": "text"},
                {"key": "ccy", "label": _("Currency"), "format": "text"},
                {"key": "amount", "label": _("Amount"), "format": "money"},
                {"key": "status", "label": _("Overdue Status"), "format": "text"},
            ],
            _("Unpaid posted invoices of the SLA sale order, in their own "
              "currency. Due date = invoice date + 30 days flat (contract "
              "rule)."),
            _("Number"), span=7, color="#1e5b96")
        widget["model"] = "account.move"
        return widget

    # ------------------------------------------------------------------
    # PDF export
    # ------------------------------------------------------------------
    @api.model
    def action_export_sla_pdf(self, customer_id=False):
        customer_id = self.sudo()._sla_selected_customer(
            {"sla_customer_id": customer_id})
        return {
            "type": "ir.actions.report",
            "report_type": "qweb-pdf",
            "report_name": "linkederp_dashboard_studio.sla_report_pdf",
            "report_file": "linkederp_dashboard_studio.sla_report_pdf",
            "name": _("Weekly Support & SLA Report"),
            "data": {"customer_id": customer_id},
            "context": dict(self.env.context, landscape=False),
        }


class SlaReport(models.AbstractModel):
    _name = "report.linkederp_dashboard_studio.sla_report_pdf"
    _description = "Weekly Support & SLA Report (PDF)"

    def _get_report_values(self, docids, data=None):
        Dashboard = self.env["linkederp.dashboard"].sudo()
        customer_id = (data or {}).get("customer_id")
        customer_id = Dashboard._sla_selected_customer(
            {"sla_customer_id": customer_id})
        values = Dashboard._sla_report_values(customer_id) if customer_id else {}
        return {
            "doc_ids": docids or [],
            "doc_model": "linkederp.dashboard",
            "docs": Dashboard.browse([]),
            "v": values,
            "short_hours": Dashboard._ops_short_hours,
            "date_text": Dashboard._ops_date_text,
            "money_text": Dashboard._ops_money,
        }
