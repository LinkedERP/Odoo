# -*- coding: utf-8 -*-
"""Add reporting/group-by helper fields to mrelate.tds.declaration.

No business-logic changes here - this module only adds stored convenience
fields for the graph/pivot dashboards (department, FY-as-int, monthly_tds
binned, regime-bucket, etc.).
"""
from odoo import api, fields, models


class TdsDeclarationReport(models.Model):
    _inherit = "mrelate.tds.declaration"

    # ------------------------------------------------------------------
    # Stored related fields - cheap, enable group-by in graph/pivot views
    # ------------------------------------------------------------------
    department_id = fields.Many2one(
        "hr.department", related="employee_id.department_id",
        store=True, readonly=True, string="Department")
    job_id = fields.Many2one(
        "hr.job", related="employee_id.job_id",
        store=True, readonly=True, string="Job")
    manager_id = fields.Many2one(
        "hr.employee", related="employee_id.parent_id",
        store=True, readonly=True, string="Manager")
    # ------------------------------------------------------------------
    # Computed buckets for dashboards
    # ------------------------------------------------------------------
    monthly_tds_bucket = fields.Selection(
        [("zero", "Zero TDS (rebate / low)"),
         ("low", "Low (< Rs 10k/mo)"),
         ("mid", "Mid (Rs 10k - 50k/mo)"),
         ("high", "High (Rs 50k - 1L/mo)"),
         ("very_high", "Very High (> Rs 1L/mo)")],
        compute="_compute_monthly_tds_bucket", store=True, readonly=True)
    fy_short = fields.Char(
        compute="_compute_fy_short", store=True, string="FY",
        help="The financial_year string, normalised for group-by in dashboards.")

    @api.depends("monthly_tds")
    def _compute_monthly_tds_bucket(self):
        for rec in self:
            m = rec.monthly_tds or 0.0
            if m <= 0:
                rec.monthly_tds_bucket = "zero"
            elif m < 10000:
                rec.monthly_tds_bucket = "low"
            elif m < 50000:
                rec.monthly_tds_bucket = "mid"
            elif m < 100000:
                rec.monthly_tds_bucket = "high"
            else:
                rec.monthly_tds_bucket = "very_high"

    @api.depends("financial_year")
    def _compute_fy_short(self):
        for rec in self:
            rec.fy_short = (rec.financial_year or "").strip() or "?"
