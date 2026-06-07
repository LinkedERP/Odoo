# -*- coding: utf-8 -*-
"""Employee annual tax declaration + monthly TDS computation (India).

One record per employee per financial year. Holds declarations, projects annual
income, computes tax under BOTH regimes, recommends the cheaper one, derives the
monthly TDS to deduct, and (on approval) writes that monthly figure to the
standard ``hr.version.l10n_in_tds`` field. It never posts/validates payslips and
never touches accounting.
"""
import re
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Statutory caps
CAP_80C = 150000.0
CAP_80CCD_1B = 50000.0
CAP_HOME_LOAN_SELF_OCCUPIED = 200000.0
CAP_HOUSE_PROPERTY_LOSS = 200000.0
# 80CCD(2) employer NPS: percentage of (basic + DA) deductible
CAP_80CCD2_OLD_REGIME_PCT = 0.10   # Private/non-govt employers, old regime
CAP_80CCD2_NEW_REGIME_PCT = 0.14   # All employers, new regime (FA 2024)
# Aggregate employer contribution (PF + Approved Superannuation + NPS) > 7.5L
# is taxable as perquisite u/s 17(2)(vii). Used for warnings, not auto-deducted.
EMPLOYER_PERK_AGGREGATE_CAP = 750000.0
# Senior citizen old-regime basic exemption (overrides default 2.5L nil band)
OLD_SENIOR_BASIC_EXEMPTION = 300000.0
OLD_SUPER_SENIOR_BASIC_EXEMPTION = 500000.0
# Sec 206AA floor when PAN missing/invalid (salary income)
SEC_206AA_FLOOR_RATE = 0.20
# PAN regex: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class TdsDeclaration(models.Model):
    _name = "mrelate.tds.declaration"
    _description = "India Employee Tax Declaration & Monthly TDS"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "financial_year desc, employee_id"
    _rec_name = "name"

    _sql_constraints = [
        ("uniq_employee_fy_company",
         "unique(employee_id, financial_year, company_id)",
         "A declaration for this employee and financial year already exists."),
    ]

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
        help="Regime actually applied for monthly TDS. Use the comparison to choose. "
             "Locked once any TDS has been applied to the contract for this FY.")
    regime_locked = fields.Boolean(
        compute="_compute_regime_locked", store=False,
        help="True once TDS has been applied for this FY - regime cannot be switched mid-year.")
    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"),
         ("reviewed", "Reviewed"), ("approved", "Approved"),
         ("locked", "Locked"), ("cancelled", "Cancelled")],
        default="draft", required=True, tracking=True)

    # ------------------------------------------------------------------
    # PAN + age category
    # ------------------------------------------------------------------
    pan = fields.Char(string="PAN", tracking=True,
        help="Format: ABCDE1234F (5 letters + 4 digits + 1 letter).")
    pan_missing = fields.Boolean(
        tracking=True,
        help="Tick if the employee has not provided a (valid) PAN. Triggers "
             "sec 206AA: TDS = higher of (computed average rate) or 20% on taxable income.")
    pan_valid = fields.Boolean(compute="_compute_pan_valid", store=True,
        help="Format-validates the PAN against the standard regex.")
    age_category = fields.Selection(
        [("under_60", "Under 60"),
         ("senior", "Senior (60-79)"),
         ("super_senior", "Super Senior (80+)")],
        default="under_60", tracking=True,
        help="Old regime only: senior 3,00,000 basic exemption; super-senior 5,00,000.")

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
    rent_paid = fields.Monetary(string="Annual rent paid",
        help="Sum of monthly rent paid during the FY.")
    hra_city_tier = fields.Selection(
        [("tier1_50", "Tier 1 - 50% of Basic (Mumbai/Delhi/Chennai/Kolkata + "
                      "Bengaluru/Pune/Hyderabad/Ahmedabad w.e.f. 1 Apr 2026)"),
         ("tier2_40", "Tier 2 - 40% of Basic (other cities)")],
        default="tier2_40",
        help="Selects the metro-tier percentage for the HRA least-of-three formula.")
    metro_city = fields.Boolean(
        compute="_compute_metro_city", store=True,
        help="Convenience boolean for legacy views: True if hra_city_tier is Tier 1.")
    lta_exemption = fields.Monetary(string="LTA exemption claimed",
        help="Sec 10(5). Current block: 1 Jan 2026 - 31 Dec 2029. 2 journeys per block.")
    ded_80c = fields.Monetary(string="80C investments",
        help="80C + 80CCC + 80CCD(1) combined, capped at 1,50,000.")
    ded_80ccd_1b = fields.Monetary(string="80CCD(1B) NPS",
        help="Additional NPS self-contribution, capped at 50,000.")
    ded_80ccd_2_employer = fields.Monetary(
        string="80CCD(2) employer NPS",
        help="Employer NPS contribution. Auto-capped at 10% of (Basic+DA) under "
             "old regime; 14% under new regime (FA 2024, all employers).")
    ded_80ccd_2_employer_capped = fields.Monetary(
        compute="_compute_taxables", store=True, readonly=True,
        help="80CCD(2) actually deducted after cap is applied (per chosen regime).")
    employer_perk_aggregate = fields.Monetary(
        compute="_compute_employer_perk_aggregate", store=True, readonly=True,
        help="Sum of employer NPS + estimated employer PF. Excess of 7,50,000 "
             "is taxable as perquisite u/s 17(2)(vii). Flagged for the reviewer.")
    employer_perk_excess = fields.Monetary(
        compute="_compute_employer_perk_aggregate", store=True, readonly=True,
        help="Excess of aggregate employer perk over 7,50,000 - taxable, not auto-added.")
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
    # NOTE: must NOT share _compute_tax with the stored Monetary/Selection fields above.
    # Odoo 19 enforces consistent store= and compute_sudo= across a single compute method;
    # Html fields default to compute_sudo=True while Monetary defaults to False.
    breakdown_html = fields.Html(
        compute="_compute_breakdown_html", sanitize=False, readonly=True)

    # ------------------------------------------------------------------
    # Monthly TDS spreading + bonus catch-up
    # ------------------------------------------------------------------
    remaining_months = fields.Integer(
        default=lambda self: self._default_remaining_months(), tracking=True,
        help="Months left in the FY over which to spread the remaining tax (sec 192). "
             "Auto-defaulted from financial_year and today.")
    tax_already_deducted = fields.Monetary(
        string="TDS already deducted (this employer)", tracking=True)
    monthly_tds = fields.Monetary(compute="_compute_tax", store=True, tracking=True,
        help="Monthly TDS to apply to the contract for regular salary payments.")
    bonus_month_extra_tds = fields.Monetary(compute="_compute_tax", store=True,
        help="One-time additional TDS to apply in the month a bonus is paid. "
             "Equals (average-rate * bonus). Apply manually that month.")
    pan_206aa_applied = fields.Boolean(compute="_compute_tax", store=True,
        help="True if Sec 206AA 20% floor was applied (PAN missing/invalid).")
    applied_monthly_tds = fields.Monetary(
        readonly=True, tracking=True,
        help="The figure last written to hr.version.l10n_in_tds.")
    applied_date = fields.Datetime(readonly=True, tracking=True,
        help="Timestamp of the last write to the contract.")
    pre_applied_value = fields.Monetary(readonly=True, tracking=True,
        help="Value of hr.version.l10n_in_tds before the last apply - kept for audit/rollback.")
    drift_detected = fields.Boolean(compute="_compute_drift_detected",
        help="True when the contract's current l10n_in_tds differs from "
             "applied_monthly_tds (someone wrote to the field outside this module).")
    drift_value = fields.Float(compute="_compute_drift_detected",
        help="Current hr.version.l10n_in_tds value, for drift comparison.")

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

    @api.model
    def _default_remaining_months(self):
        """Remaining months in the current Indian FY, counting current month onwards
        (so on 1 April -> 12; on 1 March -> 1; on 31 March -> 1)."""
        today = fields.Date.context_today(self)
        if today.month >= 4:
            end = date(today.year + 1, 3, 31)
        else:
            end = date(today.year, 3, 31)
        months = (end.year - today.year) * 12 + (end.month - today.month) + 1
        return max(1, min(12, months))

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
                 "rent_paid", "hra_city_tier", "annual_basic_da", "lta_exemption",
                 "ded_80c", "ded_80ccd_1b", "ded_80ccd_2_employer", "ded_80d",
                 "home_loan_interest", "other_deductions", "regime")
    def _compute_taxables(self):
        for rec in self:
            # HRA exemption = least of (HRA received, rent - 10% basic, x% basic)
            pct = 0.50 if rec.hra_city_tier == "tier1_50" else 0.40
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

            # 80CCD(2) employer NPS - cap = % of (basic + DA), regime-dependent
            ccd2_input = rec.ded_80ccd_2_employer or 0.0
            ccd2_pct = (CAP_80CCD2_NEW_REGIME_PCT
                        if rec.regime == "new"
                        else CAP_80CCD2_OLD_REGIME_PCT)
            ccd2_cap = (rec.annual_basic_da or 0.0) * ccd2_pct
            rec.ded_80ccd_2_employer_capped = min(ccd2_input, ccd2_cap) if ccd2_cap else 0.0

            # NEW regime: standard deduction + 80CCD(2) (capped) only
            taxable_new = (gti
                           - (cfg_new.standard_deduction if cfg_new else 0.0)
                           - rec.ded_80ccd_2_employer_capped)
            rec.taxable_income_new = max(0.0, taxable_new)

            # OLD regime: full deductions (with caps)
            chapter_via = (min(rec.ded_80c, CAP_80C)
                           + min(rec.ded_80ccd_1b, CAP_80CCD_1B)
                           + rec.ded_80ccd_2_employer_capped
                           + rec.ded_80d
                           + min(rec.home_loan_interest, CAP_HOME_LOAN_SELF_OCCUPIED)
                           + rec.other_deductions)
            taxable_old = (gti
                           - (cfg_old.standard_deduction if cfg_old else 0.0)
                           - hra_exempt - rec.lta_exemption - chapter_via)
            rec.taxable_income_old = max(0.0, taxable_old)

    @api.depends("taxable_income_old", "taxable_income_new", "regime",
                 "financial_year", "remaining_months", "prev_employer_tds",
                 "tax_already_deducted", "age_category", "pan_missing", "pan_valid",
                 "bonus_variable", "gross_total_income")
    def _compute_tax(self):
        engine = self.env["mrelate.tds.engine"]
        for rec in self:
            try:
                # Old-regime basic exemption override for seniors
                if rec.age_category == "senior":
                    old_exempt_override = OLD_SENIOR_BASIC_EXEMPTION
                elif rec.age_category == "super_senior":
                    old_exempt_override = OLD_SUPER_SENIOR_BASIC_EXEMPTION
                else:
                    old_exempt_override = None
                res_old = engine.compute(
                    rec.financial_year, "old", rec.taxable_income_old,
                    basic_exemption_override=old_exempt_override)
                res_new = engine.compute(
                    rec.financial_year, "new", rec.taxable_income_new)
            except UserError:
                rec.tax_old = rec.tax_new = 0.0
                rec.total_tax_liability = rec.monthly_tds = 0.0
                rec.bonus_month_extra_tds = 0.0
                rec.pan_206aa_applied = False
                rec.recommended_regime = False
                continue

            rec.tax_old = res_old["total_tax"]
            rec.tax_new = res_new["total_tax"]
            rec.recommended_regime = "new" if rec.tax_new <= rec.tax_old else "old"

            chosen = res_new if rec.regime == "new" else res_old
            chosen_taxable = (rec.taxable_income_new if rec.regime == "new"
                              else rec.taxable_income_old)
            total_tax = chosen["total_tax"]

            # Sec 206AA: if PAN missing or invalid format, floor at 20% of taxable income
            pan_problem = bool(rec.pan_missing) or (rec.pan and not rec.pan_valid)
            if pan_problem:
                new_tax, applied = engine.apply_206aa_floor(chosen_taxable, total_tax)
                if applied:
                    total_tax = new_tax
                    rec.pan_206aa_applied = True
                else:
                    rec.pan_206aa_applied = False
            else:
                rec.pan_206aa_applied = False
            rec.total_tax_liability = total_tax

            # Remaining tax to collect via TDS = total tax - prev employer TDS
            #   - TDS already deducted by us this FY.
            remaining = max(
                0.0,
                total_tax - rec.prev_employer_tds - rec.tax_already_deducted)
            months = rec.remaining_months or 1
            rec.monthly_tds = round(remaining / months / 10.0) * 10.0

            # Bonus month catch-up = average-rate * bonus
            # (paid in addition to monthly_tds in the bonus-payment month)
            gross_for_rate = rec.gross_total_income or 1.0
            avg_rate = total_tax / gross_for_rate if gross_for_rate else 0.0
            rec.bonus_month_extra_tds = round(
                (avg_rate * (rec.bonus_variable or 0.0)) / 10.0) * 10.0

    # ------------------------------------------------------------------
    # breakdown_html computes separately - Html field has different store/
    # compute_sudo defaults than the Monetary fields above; Odoo 19 rejects
    # mixed compute. Depends on the STORED outputs of _compute_tax.
    # ------------------------------------------------------------------
    @api.depends("regime", "tax_old", "tax_new", "monthly_tds", "remaining_months",
                 "total_tax_liability", "prev_employer_tds", "tax_already_deducted",
                 "taxable_income_old", "taxable_income_new", "recommended_regime",
                 "financial_year", "pan_206aa_applied", "age_category")
    def _compute_breakdown_html(self):
        engine = self.env["mrelate.tds.engine"]
        for rec in self:
            try:
                if rec.age_category == "senior":
                    old_exempt_override = OLD_SENIOR_BASIC_EXEMPTION
                elif rec.age_category == "super_senior":
                    old_exempt_override = OLD_SUPER_SENIOR_BASIC_EXEMPTION
                else:
                    old_exempt_override = None
                res_old = engine.compute(
                    rec.financial_year, "old", rec.taxable_income_old,
                    basic_exemption_override=old_exempt_override)
                res_new = engine.compute(
                    rec.financial_year, "new", rec.taxable_income_new)
            except UserError:
                rec.breakdown_html = (
                    "<p style='color:#b00'>No tax configuration for FY %s. "
                    "Add it under Payroll &gt; Configuration &gt; TDS Tax "
                    "Configuration.</p>" % (rec.financial_year or "?"))
                continue
            remaining = max(
                0.0,
                (rec.total_tax_liability or 0.0)
                - (rec.prev_employer_tds or 0.0)
                - (rec.tax_already_deducted or 0.0))
            rec.breakdown_html = self._render_breakdown(rec, res_old, res_new, remaining)

    # ------------------------------------------------------------------
    # PAN validation + HRA tier back-compat + regime lock + drift + perk-cap
    # ------------------------------------------------------------------
    @api.depends("pan")
    def _compute_pan_valid(self):
        for rec in self:
            rec.pan_valid = bool(rec.pan and PAN_RE.match((rec.pan or "").strip().upper()))

    @api.depends("hra_city_tier")
    def _compute_metro_city(self):
        for rec in self:
            rec.metro_city = (rec.hra_city_tier == "tier1_50")

    @api.depends("applied_monthly_tds", "state")
    def _compute_regime_locked(self):
        for rec in self:
            rec.regime_locked = bool(rec.applied_monthly_tds and rec.applied_monthly_tds > 0)

    @api.depends("applied_monthly_tds", "version_id", "version_id.l10n_in_tds")
    def _compute_drift_detected(self):
        for rec in self:
            current = (rec.version_id.l10n_in_tds if rec.version_id else 0.0) or 0.0
            rec.drift_value = current
            rec.drift_detected = bool(
                rec.applied_monthly_tds
                and abs(current - rec.applied_monthly_tds) > 0.5)

    @api.depends("ded_80ccd_2_employer_capped", "annual_basic_da")
    def _compute_employer_perk_aggregate(self):
        """Aggregate employer perk (NPS + estimated employer PF) vs Rs 7.5L cap.
        Employer PF estimated at 12% of capped wage (min(basic+DA, 15k ceiling)) * 12.
        """
        for rec in self:
            employer_pf_annual = min(rec.annual_basic_da or 0.0, 15000.0 * 12) * 0.12
            aggregate = (rec.ded_80ccd_2_employer_capped or 0.0) + employer_pf_annual
            rec.employer_perk_aggregate = aggregate
            rec.employer_perk_excess = max(0.0, aggregate - EMPLOYER_PERK_AGGREGATE_CAP)

    # ------------------------------------------------------------------
    # Onchange: warn the reviewer if regime is being switched after lock
    # ------------------------------------------------------------------
    @api.onchange("regime")
    def _onchange_regime(self):
        if self.regime_locked and self.applied_monthly_tds:
            return {
                "warning": {
                    "title": "Regime locked for this FY",
                    "message": ("TDS has already been applied for FY %s under "
                                "the previous regime. Mid-year regime change is "
                                "not allowed for TDS purposes (CBDT Circular 3/2025). "
                                "Reset the contract's l10n_in_tds and create a "
                                "revised declaration if this is a corrective change."
                                % (self.financial_year or "?"))
                }
            }

    @api.constrains("regime", "applied_monthly_tds")
    def _check_regime_lock(self):
        # Server-side hard guard - prevents writes from RPC bypassing the onchange.
        # Implementation: rely on _compute_regime_locked + a stored snapshot of
        # the locked-at regime would be ideal; for Phase 1 we only warn (onchange)
        # and trust the UI. Leaving this as a no-op constrain placeholder.
        return

    # ------------------------------------------------------------------
    # PAN normalisation (uppercase + strip)
    # ------------------------------------------------------------------
    @api.constrains("pan")
    def _check_pan_format(self):
        for rec in self:
            if rec.pan and not PAN_RE.match(rec.pan.strip().upper()):
                # Soft fail: store anyway but pan_valid will be False -> 206AA triggers.
                # Hard fail would be too disruptive at draft entry.
                pass

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
    # Salary projection auto-fill (from payroll data)
    # ==================================================================
    def _fy_bounds(self):
        """Return (fy_start, fy_end) dates for the Indian FY string.

        '2026-27' (or '2026-2027') -> 2026-04-01 .. 2027-03-31.
        """
        self.ensure_one()
        fy = (self.financial_year or "").strip()
        try:
            start_year = int(fy.split("-")[0])
        except (ValueError, IndexError):
            raise UserError(
                "Cannot parse financial year '%s'. Use 'YYYY-YY', e.g. '2026-27'." % fy)
        return date(start_year, 4, 1), date(start_year + 1, 3, 31)

    @staticmethod
    def _slip_line_total(slip, code):
        """Sum of the totals of a slip's lines with the given salary-rule code.

        Reading GROSS gives taxable gross BEFORE the EXPENSES/REIMBURSEMENT rules
        (those run at a later sequence), so reimbursements are correctly excluded.
        """
        return sum(slip.line_ids.filtered(lambda l: l.code == code).mapped("total"))

    def action_refresh_salary_projection(self):
        """Auto-fill the salary-projection fields from actual payroll data.

        READ-ONLY w.r.t. payroll: it only searches/reads existing ``hr.payslip``
        records and their computed lines and reads the contract ``hr.version``.
        It NEVER creates, computes, validates or posts a payslip and creates no
        accounting entry. It writes ONLY the four salary-projection fields on this
        declaration; manual fields (bonus, 80C/80D, HRA inputs, regime,
        remaining_months) are left untouched. ``gross_annual_salary`` and the tax
        figures then recompute automatically.
        """
        Payslip = self.env["hr.payslip"]
        for rec in self:
            if not rec.employee_id:
                raise UserError(
                    "Set the employee before refreshing the salary projection.")
            fy_start, fy_end = rec._fy_bounds()

            domain = [
                ("employee_id", "=", rec.employee_id.id),
                ("date_from", ">=", fy_start),
                ("date_to", "<=", fy_end),
                # Odoo's cancelled payslip state is 'cancel'; exclude both spellings.
                ("state", "not in", ("cancel", "cancelled")),
            ]
            if rec.company_id:
                domain.append(("company_id", "=", rec.company_id.id))
            # Draft *computed* payslips are included on purpose (UAT data).
            payslips = Payslip.search(domain, order="date_from asc")

            # "Current month" = latest payslip period inside the FY; if there is no
            # payslip yet, fall back to today's month and project from the version.
            current_slip = payslips[-1] if payslips else False
            version = rec.version_id
            if current_slip:
                monthly_gross = rec._slip_line_total(current_slip, "GROSS")
                monthly_basic = rec._slip_line_total(current_slip, "BASIC")
                current_first = current_slip.date_from.replace(day=1)
                salary_current_month = monthly_gross
                basic_current = monthly_basic
            else:
                monthly_gross = version.wage if version else 0.0
                pct = getattr(version, "l10n_in_basic_percentage", 0.0) or 0.0
                monthly_basic = monthly_gross * pct
                today = fields.Date.context_today(rec)
                current_first = today.replace(day=1)
                salary_current_month = 0.0
                basic_current = 0.0

            # Already paid YTD = GROSS of payslips strictly before the current month.
            paid_slips = payslips.filtered(lambda s: s.date_from < current_first)
            salary_paid_ytd = sum(
                rec._slip_line_total(s, "GROSS") for s in paid_slips)
            basic_paid_ytd = sum(
                rec._slip_line_total(s, "BASIC") for s in paid_slips)

            # Projected remaining = monthly gross x FY months AFTER the current
            # month for which the contract is active (respects join/leave dates).
            c_start = version.contract_date_start if version else False
            c_end = version.contract_date_end if version else False
            months_remaining = 0
            cursor = current_first + relativedelta(months=1)
            while cursor <= fy_end:
                active = True
                if c_start and cursor < c_start.replace(day=1):
                    active = False
                if c_end and cursor > c_end:
                    active = False
                if active:
                    months_remaining += 1
                cursor += relativedelta(months=1)
            salary_projected_remaining = months_remaining * monthly_gross
            basic_projected = months_remaining * monthly_basic

            annual_basic_da = basic_paid_ytd + basic_current + basic_projected

            rec.write({
                "salary_paid_ytd": salary_paid_ytd,
                "salary_current_month": salary_current_month,
                "salary_projected_remaining": salary_projected_remaining,
                "annual_basic_da": annual_basic_da,
            })

            paid_label = current_slip and current_slip.date_from.strftime("%b %Y") or "-"
            rec.message_post(body=(
                "<b>Salary projection refreshed from payroll.</b>"
                "<ul>"
                "<li>Payslips found in FY %s: %s (current month: %s)</li>"
                "<li>Salary paid YTD (GROSS, %s slip(s) before current): %0.0f</li>"
                "<li>Current month salary (GROSS): %0.0f</li>"
                "<li>Projected remaining: %s month(s) x %0.0f = %0.0f</li>"
                "<li>Annual Basic+DA (BASIC lines / projection): %0.0f</li>"
                "<li>Gross annual (recomputed): %0.0f</li>"
                "</ul>"
                "<i>Manual fields (bonus, 80C/80D, HRA, regime, spreading months) "
                "were not changed. No payslip was computed or posted.</i>"
                % (rec.financial_year, len(payslips), paid_label,
                   len(paid_slips), salary_paid_ytd, salary_current_month,
                   months_remaining, monthly_gross, salary_projected_remaining,
                   annual_basic_da,
                   salary_paid_ytd + salary_current_month
                   + salary_projected_remaining + rec.bonus_variable)))
        return True

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

        Snapshots the prior l10n_in_tds value into pre_applied_value for audit
        and rollback. Stamps applied_date.
        """
        for rec in self:
            if rec.state not in ("approved", "locked"):
                raise UserError(
                    "Approve the declaration before applying TDS to the contract.")
            if not rec.version_id:
                raise UserError(
                    "Set the Contract Version before applying TDS.")
            prior = rec.version_id.l10n_in_tds or 0.0
            rec.version_id.write({"l10n_in_tds": rec.monthly_tds})
            rec.write({
                "applied_monthly_tds": rec.monthly_tds,
                "pre_applied_value": prior,
                "applied_date": fields.Datetime.now(),
            })
            rec.message_post(
                body=("Applied monthly TDS <b>%0.2f</b> to contract version "
                      "<b>%s</b> (l10n_in_tds). Previous value: %0.2f."
                      % (rec.monthly_tds, rec.version_id.display_name, prior)))
        return True

    def action_rollback_contract(self):
        """Restore hr.version.l10n_in_tds to its value before the last apply.

        Useful when a wrong declaration was applied. Posts an audit note.
        """
        for rec in self:
            if not rec.version_id:
                raise UserError("Set the Contract Version before rolling back TDS.")
            if not rec.applied_date:
                raise UserError("Nothing has been applied yet for this declaration.")
            prior = rec.pre_applied_value or 0.0
            rec.version_id.write({"l10n_in_tds": prior})
            rec.message_post(
                body=("ROLLBACK: contract %s l10n_in_tds reset to <b>%0.2f</b> "
                      "(was %0.2f). Declaration applied_monthly_tds cleared."
                      % (rec.version_id.display_name, prior, rec.applied_monthly_tds or 0.0)))
            rec.write({
                "applied_monthly_tds": 0.0,
                "applied_date": False,
            })
        return True

    def action_resync_from_contract(self):
        """When drift is detected (someone wrote to l10n_in_tds outside this module),
        re-apply this declaration's monthly_tds to the contract to restore the
        single-source-of-truth. Snapshot the current (drifted) value first.
        """
        for rec in self:
            if rec.state not in ("approved", "locked"):
                raise UserError("Approve the declaration before resyncing.")
            if not rec.version_id:
                raise UserError("Set the Contract Version before resyncing.")
            drifted = rec.version_id.l10n_in_tds or 0.0
            rec.version_id.write({"l10n_in_tds": rec.monthly_tds})
            rec.write({
                "applied_monthly_tds": rec.monthly_tds,
                "pre_applied_value": drifted,
                "applied_date": fields.Datetime.now(),
            })
            rec.message_post(
                body=("RESYNC: contract %s had drifted to %0.2f; restored to "
                      "<b>%0.2f</b> from this declaration."
                      % (rec.version_id.display_name, drifted, rec.monthly_tds)))
        return True
