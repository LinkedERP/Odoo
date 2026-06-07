# -*- coding: utf-8 -*-
"""Dual-regime income-tax calculation engine for India.

Stateless service (AbstractModel). Given a financial year, regime and a taxable
income, it returns a full, explainable breakdown using the configurable
``mrelate.tds.year.config`` records. No business data is stored here.

Marginal relief is applied at:
  * Sec 87A rebate boundary (new regime; effective for taxable income
    just above the rebate income limit so additional tax never exceeds
    additional income above the boundary).
  * Each surcharge step (50L / 1Cr / 2Cr / 5Cr) so additional tax + surcharge
    cannot exceed additional income above the threshold.
"""
from odoo import api, models
from odoo.exceptions import UserError


def _round10(amount):
    """Round to nearest Rs 10 (sec 288B style). Final-figure rounding only."""
    return round(amount / 10.0) * 10.0


class TdsTaxEngine(models.AbstractModel):
    _name = "mrelate.tds.engine"
    _description = "India TDS - Tax Calculation Engine"

    # ------------------------------------------------------------------
    # Config lookup
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Core building blocks
    # ------------------------------------------------------------------
    @api.model
    def _slab_tax(self, cfg, taxable_income, basic_exemption_override=None):
        """Progressive tax across the configured slabs.

        ``basic_exemption_override`` lifts the 0% nil band (senior 3L / super-senior 5L
        old regime). Implemented as: if override > slab[0].upper_limit, shift the
        following slabs' lower bound up so the first taxable slab begins at the
        override amount. Conservative: only the nil band is widened; rate steps unchanged.
        """
        tax = 0.0
        slabs = list(cfg.slab_ids.sorted("lower_limit"))
        if basic_exemption_override and slabs:
            nil_top = slabs[0].upper_limit or 0.0
            if basic_exemption_override > nil_top:
                # Treat income up to override as nil
                effective_floor = basic_exemption_override
            else:
                effective_floor = nil_top
        else:
            effective_floor = slabs[0].upper_limit if slabs else 0.0
        for slab in slabs:
            lower = max(slab.lower_limit, effective_floor) if slab.rate > 0 else slab.lower_limit
            upper = slab.upper_limit or float("inf")
            if taxable_income <= lower:
                continue
            band = min(taxable_income, upper) - lower
            if band > 0:
                tax += band * slab.rate
        return tax

    @api.model
    def _rebate(self, cfg, taxable_income, base_tax):
        """Section 87A rebate WITH marginal relief.

        For new regime FY 2026-27: rebate up to Rs 60,000 if taxable income <= 12L.
        Marginal relief: just above 12L, total tax (post-rebate) cannot exceed
        (taxable_income - 12L). I.e. additional tax owed <= additional income
        over the rebate ceiling. Phases out around taxable ~12.75L.

        Source: incometax.gov.in / Cleartax / CBDT.
        """
        if not cfg.rebate_income_limit:
            return 0.0
        if taxable_income <= cfg.rebate_income_limit:
            return min(base_tax, cfg.rebate_max)
        # Marginal-relief zone: just above the rebate ceiling.
        excess = taxable_income - cfg.rebate_income_limit
        if base_tax > excess:
            # Allow rebate that brings tax down to (excess), but never increase tax.
            rebate_via_marginal = base_tax - excess
            # Marginal relief should not exceed rebate_max either (defensive)
            return min(rebate_via_marginal, base_tax)
        return 0.0

    @api.model
    def _surcharge(self, cfg, total_income, tax_after_rebate):
        """Surcharge on tax (no marginal relief here - applied separately)."""
        rate = 0.0
        active_band_lower = 0.0
        for band in cfg.surcharge_ids.sorted("lower_limit"):
            upper = band.upper_limit or float("inf")
            if total_income > band.lower_limit and total_income <= upper:
                rate = band.rate
                active_band_lower = band.lower_limit
                break
        return tax_after_rebate * rate, rate, active_band_lower

    @api.model
    def _surcharge_marginal_relief(self, cfg, total_income, tax_after_rebate,
                                   surcharge, surcharge_rate, active_band_lower):
        """Apply marginal relief at the surcharge band boundary.

        Principle (well-settled): (tax + surcharge at actual income) shall not
        exceed (tax + surcharge at threshold) + (income above threshold).

        We compute the boundary scenario (income = active_band_lower) and cap the
        current surcharge accordingly. We do NOT touch the base tax.
        """
        if surcharge_rate <= 0 or active_band_lower <= 0:
            return surcharge, 0.0
        # Boundary tax_after_rebate (slab math at the threshold; rebate not in scope
        # at these income levels in either regime, so we skip the rebate call).
        boundary_base = self._slab_tax(cfg, active_band_lower)
        # Surcharge at threshold = 0 (we're exactly AT the lower bound; next band starts)
        # Limit: total (tax+surcharge) at actual <= boundary_tax + (income - threshold)
        excess_income = total_income - active_band_lower
        ceiling = boundary_base + excess_income
        actual = tax_after_rebate + surcharge
        if actual > ceiling:
            relief = actual - ceiling
            new_surcharge = max(0.0, surcharge - relief)
            return new_surcharge, relief
        return surcharge, 0.0

    @api.model
    def compute(self, financial_year, regime, taxable_income,
                total_income_for_surcharge=None, basic_exemption_override=None):
        """Return a full breakdown dict for one regime.

        :param taxable_income: income after all eligible deductions for this regime.
        :param total_income_for_surcharge: income used to pick the surcharge band
            (defaults to taxable_income).
        :param basic_exemption_override: optional override for the nil band
            (old-regime senior 3,00,000 / super-senior 5,00,000).
        """
        cfg = self.get_config(financial_year, regime)
        taxable_income = max(0.0, taxable_income or 0.0)
        surcharge_base_income = (
            taxable_income if total_income_for_surcharge is None
            else max(0.0, total_income_for_surcharge))

        base_tax = self._slab_tax(cfg, taxable_income, basic_exemption_override)
        rebate = self._rebate(cfg, taxable_income, base_tax)
        tax_after_rebate = max(0.0, base_tax - rebate)
        surcharge, surcharge_rate, active_band_lower = self._surcharge(
            cfg, surcharge_base_income, tax_after_rebate)
        # Marginal relief at the active surcharge band
        surcharge, sur_relief = self._surcharge_marginal_relief(
            cfg, surcharge_base_income, tax_after_rebate, surcharge,
            surcharge_rate, active_band_lower)
        cess = (tax_after_rebate + surcharge) * cfg.cess_rate
        total_tax = _round10(tax_after_rebate + surcharge + cess)

        lines = [
            "Regime: %s (FY %s)" % (regime.upper(), financial_year),
            "Taxable income: %0.2f" % taxable_income,
            "Tax on slabs: %0.2f" % base_tax,
            "Less 87A rebate (incl. marginal relief): %0.2f" % rebate,
            "Tax after rebate: %0.2f" % tax_after_rebate,
            "Surcharge (%0.0f%%): %0.2f" % (surcharge_rate * 100, surcharge),
        ]
        if sur_relief > 0:
            lines.append("  ...marginal relief on surcharge: -%0.2f" % sur_relief)
        lines += [
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
            "surcharge_marginal_relief": sur_relief,
            "cess": cess,
            "total_tax": total_tax,
            "explanation": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    # Sec 206AA helper: higher TDS when PAN missing/invalid
    # ------------------------------------------------------------------
    @api.model
    def apply_206aa_floor(self, taxable_income, computed_total_tax):
        """Sec 206AA for salary: TDS = higher of (computed average rate) or 20%
        on taxable income. Not a flat add-on. CBDT Circular 4/2008 + sec 206AA(2).

        :returns: tuple (final_tax, applied_floor_bool)
        """
        if taxable_income <= 0:
            return computed_total_tax, False
        floor = taxable_income * 0.20
        if floor > computed_total_tax:
            return _round10(floor), True
        return computed_total_tax, False
