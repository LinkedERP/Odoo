# -*- coding: utf-8 -*-
"""Configurable, data-driven tax-rate configuration.

All statutory numbers (slabs, standard deduction, rebate, surcharge, cess) live
in these records, NOT in Python. Adding a future financial year = adding data,
never editing code. Seed data for FY 2026-27 is in data/tds_fy_2026_27_data.xml.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class TdsYearConfig(models.Model):
    _name = "mrelate.tds.year.config"
    _description = "India TDS - Yearly Tax Configuration (per regime)"
    _order = "financial_year desc, regime"

    name = fields.Char(compute="_compute_name", store=True)
    financial_year = fields.Char(
        required=True,
        help="Indian financial year, e.g. '2026-27' (April 2026 - March 2027).",
    )
    regime = fields.Selection(
        [("new", "New Regime (115BAC)"), ("old", "Old Regime")],
        required=True,
        default="new",
    )
    active = fields.Boolean(default=True)

    standard_deduction = fields.Float(
        help="Standard deduction for salaried individuals under this regime.")
    rebate_income_limit = fields.Float(
        help="Section 87A: taxable income at or below this gets the rebate.")
    rebate_max = fields.Float(
        help="Section 87A: maximum rebate amount.")
    basic_exemption = fields.Float(
        help="Basic exemption limit (informational / age-based extensions in Phase 2).")
    cess_rate = fields.Float(
        default=0.04, help="Health & education cess as a fraction (0.04 = 4%).")
    surcharge_capped = fields.Boolean(
        help="If set, the highest surcharge band caps here (e.g. new regime caps at 25%).")

    slab_ids = fields.One2many(
        "mrelate.tds.slab", "config_id", string="Tax Slabs")
    surcharge_ids = fields.One2many(
        "mrelate.tds.surcharge.band", "config_id", string="Surcharge Bands")

    # Odoo 19 removed _sql_constraints. Replaced by a Python @api.constrains
    # below that searches for an existing row with the same (financial_year, regime).
    @api.constrains("financial_year", "regime")
    def _check_unique_year_regime(self):
        for rec in self:
            if not (rec.financial_year and rec.regime):
                continue
            existing = self.search([
                ("financial_year", "=", rec.financial_year),
                ("regime", "=", rec.regime),
                ("id", "!=", rec.id),
            ], limit=1)
            if existing:
                raise ValidationError(
                    "A configuration for FY %s (%s regime) already exists."
                    % (rec.financial_year, rec.regime))

    @api.depends("financial_year", "regime")
    def _compute_name(self):
        labels = dict(self._fields["regime"].selection)
        for rec in self:
            rec.name = "FY %s - %s" % (
                rec.financial_year or "?", labels.get(rec.regime, rec.regime or ""))

    @api.constrains("cess_rate")
    def _check_cess(self):
        for rec in self:
            if rec.cess_rate < 0 or rec.cess_rate > 1:
                raise ValidationError("Cess rate must be a fraction between 0 and 1.")


class TdsSlab(models.Model):
    _name = "mrelate.tds.slab"
    _description = "India TDS - Income Tax Slab"
    _order = "config_id, sequence, lower_limit"

    config_id = fields.Many2one(
        "mrelate.tds.year.config", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    lower_limit = fields.Float(
        required=True, help="Lower bound of the slab (inclusive of amount above it).")
    upper_limit = fields.Float(
        help="Upper bound of the slab. Use 0 for the top (open-ended) slab.")
    rate = fields.Float(
        required=True, help="Marginal rate as a fraction (0.05 = 5%).")

    @api.constrains("rate")
    def _check_rate(self):
        for rec in self:
            if rec.rate < 0 or rec.rate > 1:
                raise ValidationError("Slab rate must be a fraction between 0 and 1.")


class TdsSurchargeBand(models.Model):
    _name = "mrelate.tds.surcharge.band"
    _description = "India TDS - Surcharge Band"
    _order = "config_id, sequence, lower_limit"

    config_id = fields.Many2one(
        "mrelate.tds.year.config", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    lower_limit = fields.Float(
        required=True, help="Total income above this amount attracts this surcharge.")
    upper_limit = fields.Float(
        help="Total income up to this amount. Use 0 for the top (open-ended) band.")
    rate = fields.Float(
        required=True, help="Surcharge rate as a fraction (0.10 = 10%).")
