# -*- coding: utf-8 -*-
"""Dual-regime income-tax calculation engine.

Stateless service (AbstractModel). Given a financial year, regime and a taxable
income, it returns a full, explainable breakdown using the configurable
``mrelate.tds.year.config`` records. No business data is stored here.

IMPORTANT (flagged for CA/payroll validation):
  * Marginal relief at the 87A rebate boundary (new regime) is NOT applied.
  * Surcharge marginal relief at the 50L/1Cr/2Cr/5Cr boundaries is NOT applied.
  These approximations can over-state tax for incomes just above a boundary.
  See README.md "Items requiring CA/payroll validation".
"""
from odoo import api, models
from odoo.exceptions import UserError


def _round10(amount):
    """Round to nearest Rs 10 (sec 288B style). Final-figure rounding only."""
    return round(amount / 10.0) * 10.0


class TdsTaxEngine(models.AbstractModel):
    _name = "mrelate.tds.engine"
    _description = "India TDS - Tax Calculation Engine"

    @api.model
    def get_config(self, financial_year, regime):
        cfg = self.env["mrelate.tds.year.config"].search([
            ("financial_year", "=", financial_year),
            ("regime", "=", regime),
        ], limit=1)
        if not cfg:
            raise UserError(
                "No tax configuration found for FY %s (%s regime). "
                "Add it under Payroll > Configuration > TDS Tax Configuration."
                % (financial_year, regime))
        return cfg

    @api.model
    def _slab_tax(self, cfg, taxable_income):
        """Progressive tax across the configured slabs."""
        tax = 0.0
        for slab in cfg.slab_ids.sorted("lower_limit"):
            lower = slab.lower_limit
            upper = slab.upper_limit or float("inf")
            if taxable_income <= lower:
                continue
            band = min(taxable_income, upper) - lower
            if band > 0:
                tax += band * slab.rate
        return tax

    @api.model
    def _rebate(self, cfg, taxable_income, base_tax):
        """Section 87A rebate (no marginal relief in Phase 1 - flagged)."""
        if cfg.rebate_income_limit and taxable_income <= cfg.rebate_income_limit:
            return min(base_tax, cfg.rebate_max)
        return 0.0

    @api.model
    def _surcharge(self, cfg, total_income, tax_after_rebate):
        """Surcharge on tax, by total-income band (no marginal relief - flagged)."""
        rate = 0.0
        for band in cfg.surcharge_ids.sorted("lower_limit"):
            upper = band.upper_limit or float("inf")
            if total_income > band.lower_limit and total_income <= upper:
                rate = band.rate
                break
            if total_income > band.lower_limit and band.upper_limit == 0:
                rate = band.rate
        return tax_after_rebate * rate, rate

    @api.model
    def compute(self, financial_year, regime, taxable_income, total_income_for_surcharge=None):
        """Return a full breakdown dict for one regime.

        :param taxable_income: income after all eligible deductions for this regime.
        :param total_income_for_surcharge: income used to pick the surcharge band
            (defaults to taxable_income).
        :returns: dict with every intermediate figure + a text explanation.
        """
        cfg = self.get_config(financial_year, regime)
        taxable_income = max(0.0, taxable_income or 0.0)
        surcharge_base_income = (
            taxable_income if total_income_for_surcharge is None
            else max(0.0, total_income_for_surcharge))

        base_tax = self._slab_tax(cfg, taxable_income)
        rebate = self._rebate(cfg, taxable_income, base_tax)
        tax_after_rebate = max(0.0, base_tax - rebate)
        surcharge, surcharge_rate = self._surcharge(
            cfg, surcharge_base_income, tax_after_rebate)
        cess = (tax_after_rebate + surcharge) * cfg.cess_rate
        total_tax = _round10(tax_after_rebate + surcharge + cess)

        lines = [
            "Regime: %s (FY %s)" % (regime.upper(), financial_year),
            "Taxable income: %0.2f" % taxable_income,
            "Tax on slabs: %0.2f" % base_tax,
            "Less 87A rebate: %0.2f" % rebate,
            "Tax after rebate: %0.2f" % tax_after_rebate,
            "Surcharge (%0.0f%%): %0.2f" % (surcharge_rate * 100, surcharge),
            "Health & education cess (%0.0f%%): %0.2f" % (cfg.cess_rate * 100, cess),
            "Total tax (rounded to nearest 10): %0.2f" % total_tax,
        ]
        return {
            "regime": regime,
            "financial_year": financial_year,
            "taxable_income": taxable_income,
            "base_tax": base_tax,
            "rebate": rebate,
            "tax_after_rebate": tax_after_rebate,
            "surcharge_rate": surcharge_rate,
            "surcharge": surcharge,
            "cess": cess,
            "total_tax": total_tax,
            "explanation": "\n".join(lines),
        }
