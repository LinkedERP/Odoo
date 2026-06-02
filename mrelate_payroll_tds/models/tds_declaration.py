# -*- coding: utf-8 -*-
"""Employee annual tax declaration + monthly TDS computation.

One record per employee per financial year. Holds declarations, projects annual
income, computes tax under BOTH regimes, recommends the cheaper one, derives the
monthly TDS to deduct, and (on approval) writes that monthly figure to the
standard ``hr.version.l10n_in_tds`` field. It never posts/validates payslips and
never touches accounting.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

# Statutory caps applied during computation (Phase 1). Flagged for CA validation.
CAP_80C = 150000.0
CAP_80CCD_1B = 50000.0
CAP_HOME_LOAN_SELF_OCCUPIED = 200000.0
CAP_HOUSE_PROPERTY_LOSS = 200000.0


class TdsDeclaration(models.Model):
    _name = "mrelate.tds.declaration"
    _description = "India Employee Tax Declaration & Monthly TDS"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "financial_year desc, employee_id"
    _rec_name = "name"

    # ------------------------------------------------------------------
    # Identity / context
    # ------------------------------------------------------------------
    name = fields.Char(compute="_compute_name", store=True)
    employee_id = fields.Many2one(
        "hr.employee", required=True, tracking=True,
        help="Employee this declaration belongs to.")
    version_id = fields.Many2one(
        "hr.version", string="Contract Version", tracking=True,
        help="Salary version whose l10n_in_tds field will receive the monthly TDS.")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True)
    financial_year = fields.Char(
        required=True, default=lambda self: self._default_financial_year(),
        tracking=True, help="e.g. '2026-27'.")
    regime = fields.Selection(
        [("new", "New Regime (115BAC)"), ("old", "Old Regime")],
        default="new", required=True, tracking=True,
        help="Regime actually applied for monthly TDS. Use the comparison to choose.")
    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"),
         ("reviewed", "Reviewed"), ("approved", "Approved"),
         ("locked", "Locked"), ("cancelled", "Cancelled")],
        default="draft", required=True, tracking=True)

    # ------------------------------------------------------------------
    # PAN
    # ------------------------------------------------------------------
    pan = fields.Char(string="PAN", tracking=True)
    pan_missing = fields.Boolean(
        tracking=True,
        help="Tick if the employee has not provided a PAN. Higher TDS may apply "
             "under sec 206AA - flagged for CA validation, not auto-applied in Phase 1.")

    # ------------------------------------------------------------------
    # Salary projection (Phase 1)
    # ------------------------------------------------------------------
    salary_paid_ytd = fields.Monetary(
        string="Salary already paid (YTD)", tracking=True,
        help="Taxable salary already paid by THIS employer in the FY so far.")
    salary_current_month = fields.Monetary(string="Current month salary", tracking=True)
    salary_projected_remaining = fields.Monetary(
        string="Projected remaining salary", tracking=True,
        help="Projected taxable salary for the rest of the FY (excl. current month).")
    bonus_variable = fields.Monetary(
        string="Bonus / variable / one-time", tracking=True)
    annual_basic_da = fields.Monetary(
        string="Annual Basic + DA", help="Used for the HRA exemption formula (old regime).")
    gross_annual_salary = fields.Monetary(
        compute="_compute_gross_annual_salary", store=True, tracking=True)

    # ------------------------------------------------------------------
    # Other income / previous employer
    # ------------------------------------------------------------------
    prev_employer_income = fields.Monetary(string="Previous employer income", tracking=True)
    prev_employer_tds = fields.Monetary(string="Previous employer TDS", tracking=True)
    other_income = fields.Monetary(string="Other income", tracking=True)
    interest_income = fields.Monetary(string="Interest income", tracking=True)
    house_property_income = fields.Monetary(
        string="House property income / (loss)", tracking=True,
        help="Negative for a loss. Loss set-off is capped at 2,00,000 (flagged).")

    # ------------------------------------------------------------------
    # Exemptions & deductions (mainly old regime)
    # ------------------------------------------------------------------
    hra_received = fields.Monetary(string="HRA received (annual)")
    rent_paid = fields.Monetary(string="Annual rent paid")
    metro_city = fields.Boolean(
        string="Lives in metro city", help="50% of basic if metro, else 40%.")
    lta_exemption = fields.Monetary(string="LTA exemption claimed")
    ded_80c = fields.Monetary(string="80C investments", help="Capped at 1,50,000.")
    ded_80ccd_1b = fields.Monetary(string="80CCD(1B) NPS", help="Capped at 50,000.")
    ded_80ccd_2_employer = fields.Monetary(
        string="80CCD(2) employer NPS",
        help="Employer NPS contribution. Allowed under BOTH regimes (limit flagged).")
    ded_80d = fields.Monetary(string="80D medical insurance")
    home_loan_interest = fields.Monetary(
        string="Home-loan interest (sec 24b)", help="Self-occupied capped at 2,00,000.")
    other_deductions = fields.Monetary(string="Other deductions (old regime)")

    # ------------------------------------------------------------------
    # Computed exemptions / taxable incomes
    # ------------------------------------------------------------------
    hra_exempt = fields.Monetary(compute="_compute_taxables", store=True)
    gross_total_income = fields.Monetary(compute="_compute_taxables", store=True)
    taxable_income_old = fields.Monetary(compute="_compute_taxables", store=True)
    taxable_income_new = fields.Monetary(compute="_compute_taxables", store=True)

    # ------------------------------------------------------------------
    # Computed tax (both regimes)
    # ------------------------------------------------------------------
    tax_old = fields.Monetary(compute="_compute_tax", store=True)
    tax_new = fields.Monetary(compute="_compute_tax", store=True)
    recommended_regime = fields.Selection(
        [("new", "New Regime (115BAC)"), ("old", "Old Regime")],
        compute="_compute_tax", store=True)
    total_tax_liability = fields.Monetary(compute="_compute_tax", store=True,
        help="Tax for the regime selected on this declaration.")
    breakdown_html = fields.Html(compute="_compute_tax", sanitize=False, readonly=True)

    # ------------------------------------------------------------------
    # Monthly TDS spreading
    # ------------------------------------------------------------------
    remaining_months = fields.Integer(
        default=12, tracking=True,
        help="Months left in the FY over which to spread the remaining tax (sec 192).")
    tax_already_deducted = fields.Monetary(
        string="TDS already deducted (this employer)", tracking=True)
    monthly_tds = fields.Monetary(compute="_compute_tax", store=True, tracking=True,
        help="Monthly TDS to apply to the contract.")
    applied_monthly_tds = fields.Monetary(
        readonly=True, tracking=True,
        help="The figure last written to hr.version.l10n_in_tds.")

    # ==================================================================
    # Defaults
    # ==================================================================
    @api.model
    def _default_financial_year(self):
        """Indian FY string for today (Apr-Mar). Date.today is fine server-side."""
        today = fields.Date.context_today(self)
        year = today.year
        if today.month < 4:  # Jan-Mar belongs to the FY that started last April
            start = year - 1
        else:
            start = year
        return "%s-%s" % (start, str(start + 1)[-2:])

    # ==================================================================
    # Computes
    # ==================================================================
    @api.depends("employee_id", "financial_year")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s - FY %s" % (
                rec.employee_id.name or "New", rec.financial_year or "?")

    @api.depends("salary_paid_ytd", "salary_current_month",
                 "salary_projected_remaining", "bonus_variable")
    def _compute_gross_annual_salary(self):
        for rec in self:
            rec.gross_annual_salary = (
                rec.salary_paid_ytd + rec.salary_current_month
                + rec.salary_projected_remaining + rec.bonus_variable)

    @api.depends("gross_annual_salary", "prev_employer_income", "other_income",
                 "interest_income", "house_property_income", "hra_received",
                 "rent_paid", "metro_city", "annual_basic_da", "lta_exemption",
                 "ded_80c", "ded_80ccd_1b", "ded_80ccd_2_employer", "ded_80d",
                 "home_loan_interest", "other_deductions")
    def _compute_taxables(self):
        for rec in self:
            # HRA exemption = least of (HRA received, rent - 10% basic, x% basic)
            pct = 0.50 if rec.metro_city else 0.40
            hra_exempt = 0.0
            if rec.hra_received and rec.rent_paid:
                hra_exempt = max(0.0, min(
                    rec.hra_received,
                    rec.rent_paid - 0.10 * rec.annual_basic_da,
                    pct * rec.annual_basic_da,
                ))
            rec.hra_exempt = hra_exempt

            # House-property loss capped at 2,00,000 of set-off
            hp = rec.house_property_income
            if hp < 0:
                hp = max(hp, -CAP_HOUSE_PROPERTY_LOSS)

            gti = (rec.gross_annual_salary + rec.prev_employer_income
                   + rec.other_income + rec.interest_income + hp)
            rec.gross_total_income = gti

            cfg_new = self._cfg("new", rec)
            cfg_old = self._cfg("old", rec)

            # NEW regime: standard deduction + 80CCD(2) only
            taxable_new = (gti
                           - (cfg_new.standard_deduction if cfg_new else 0.0)
                           - rec.ded_80ccd_2_employer)
            rec.taxable_income_new = max(0.0, taxable_new)

            # OLD regime: full deductions (with caps)
            chapter_via = (min(rec.ded_80c, CAP_80C)
                           + min(rec.ded_80ccd_1b, CAP_80CCD_1B)
                           + rec.ded_80ccd_2_employer
                           + rec.ded_80d
                           + min(rec.home_loan_interest, CAP_HOME_LOAN_SELF_OCCUPIED)
                           + rec.other_deductions)
            taxable_old = (gti
                           - (cfg_old.standard_deduction if cfg_old else 0.0)
                           - hra_exempt - rec.lta_exemption - chapter_via)
            rec.taxable_income_old = max(0.0, taxable_old)

    @api.depends("taxable_income_old", "taxable_income_new", "regime",
                 "financial_year", "remaining_months", "prev_employer_tds",
                 "tax_already_deducted")
    def _compute_tax(self):
        engine = self.env["mrelate.tds.engine"]
        for rec in self:
            try:
                res_old = engine.compute(
                    rec.financial_year, "old", rec.taxable_income_old)
                res_new = engine.compute(
                    rec.financial_year, "new", rec.taxable_income_new)
            except UserError:
                # Config missing for this FY - leave zeros, surface in the UI text
                rec.tax_old = rec.tax_new = 0.0
                rec.total_tax_liability = rec.monthly_tds = 0.0
                rec.recommended_regime = False
                rec.breakdown_html = (
                    "<p style='color:#b00'>No tax configuration for FY %s. "
                    "Add it under Payroll &gt; Configuration &gt; TDS Tax "
                    "Configuration.</p>" % (rec.financial_year or "?"))
                continue

            rec.tax_old = res_old["total_tax"]
            rec.tax_new = res_new["total_tax"]
            rec.recommended_regime = "new" if rec.tax_new <= rec.tax_old else "old"

            chosen = res_new if rec.regime == "new" else res_old
            rec.total_tax_liability = chosen["total_tax"]

            # Remaining tax to collect via TDS = total tax - prev employer TDS
            #   - TDS already deducted by us this FY.
            remaining = max(
                0.0,
                chosen["total_tax"] - rec.prev_employer_tds - rec.tax_already_deducted)
            months = rec.remaining_months or 1
            rec.monthly_tds = round(remaining / months / 10.0) * 10.0

            rec.breakdown_html = self._render_breakdown(rec, res_old, res_new, remaining)

    # ==================================================================
    # Helpers
    # ==================================================================
    def _cfg(self, regime, rec):
        return self.env["mrelate.tds.year.config"].search([
            ("financial_year", "=", rec.financial_year),
            ("regime", "=", regime),
        ], limit=1)

    def _render_breakdown(self, rec, res_old, res_new, remaining):
        def block(res, chosen):
            star = " &#9733;" if chosen else ""
            rows = "".join(
                "<tr><td>%s</td><td style='text-align:right'>%s</td></tr>" % (k, v)
                for k, v in [
                    ("Taxable income", "%0.0f" % res["taxable_income"]),
                    ("Tax on slabs", "%0.0f" % res["base_tax"]),
                    ("Less 87A rebate", "%0.0f" % res["rebate"]),
                    ("Tax after rebate", "%0.0f" % res["tax_after_rebate"]),
                    ("Surcharge (%0.0f%%)" % (res["surcharge_rate"] * 100),
                     "%0.0f" % res["surcharge"]),
                    ("Cess", "%0.0f" % res["cess"]),
                    ("<b>Total tax</b>", "<b>%0.0f</b>" % res["total_tax"]),
                ])
            return ("<div style='display:inline-block;vertical-align:top;"
                    "margin-right:24px'><h4>%s regime%s</h4>"
                    "<table class='table table-sm'>%s</table></div>") % (
                        res["regime"].upper(), star, rows)

        chosen_new = rec.regime == "new"
        header = (
            "<p><b>Recommended regime:</b> %s &nbsp; | &nbsp; "
            "<b>Applied regime:</b> %s</p>"
            % ((rec.recommended_regime or "?").upper(), rec.regime.upper()))
        footer = (
            "<hr/><p><b>Remaining tax to collect:</b> %0.0f "
            "(total %0.0f &minus; prev-employer TDS %0.0f &minus; already deducted %0.0f)"
            "<br/><b>Spread over:</b> %s month(s) &nbsp; &rarr; &nbsp; "
            "<b>Monthly TDS: %0.0f</b></p>"
            % (remaining, rec.total_tax_liability, rec.prev_employer_tds,
               rec.tax_already_deducted, rec.remaining_months, rec.monthly_tds))
        return header + block(res_old, not chosen_new) + block(res_new, chosen_new) + footer

    # ==================================================================
    # Workflow
    # ==================================================================
    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError("Only draft declarations can be submitted.")
            if rec.pan_missing:
                rec.message_post(body="Submitted with PAN missing flag set.")
        self.write({"state": "submitted"})

    def action_review(self):
        self._ensure_state("submitted", "reviewed")

    def action_approve(self):
        self._ensure_state("reviewed", "approved")

    def action_lock(self):
        self._ensure_state("approved", "locked")

    def action_reset_draft(self):
        for rec in self:
            if rec.state == "locked":
                raise UserError(
                    "A locked declaration cannot be reset. Create a revision instead.")
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def _ensure_state(self, from_state, to_state):
        for rec in self:
            if rec.state != from_state:
                raise UserError(
                    "Declaration must be '%s' to move to '%s'." % (from_state, to_state))
        self.write({"state": to_state})

    # ==================================================================
    # Write-back to the standard contract field
    # ==================================================================
    def action_apply_to_contract(self):
        """Write monthly_tds to hr.version.l10n_in_tds.

        SAFETY: only allowed on approved/locked records. Writes a single float to
        an existing field. Does NOT compute, validate or post any payslip, and
        creates no accounting entry.
        """
        for rec in self:
            if rec.state not in ("approved", "locked"):
                raise UserError(
                    "Approve the declaration before applying TDS to the contract.")
            if not rec.version_id:
                raise UserError(
                    "Set the Contract Version before applying TDS.")
            rec.version_id.write({"l10n_in_tds": rec.monthly_tds})
            rec.applied_monthly_tds = rec.monthly_tds
            rec.message_post(
                body="Applied monthly TDS %0.2f to contract version %s (l10n_in_tds)."
                     % (rec.monthly_tds, rec.version_id.display_name))
        return True
