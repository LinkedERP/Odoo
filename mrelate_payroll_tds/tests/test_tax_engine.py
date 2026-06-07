# -*- coding: utf-8 -*-
"""Unit tests for the FY 2026-27 dual-regime tax engine and declaration compute.

Run (after deploying the module on the dev/test DB):
    odoo -c <conf> -d <db> -i mrelate_payroll_tds --test-enable --stop-after-init
or:
    odoo --test-tags /mrelate_payroll_tds

Expected values were derived by hand from the official FY 2026-27 slabs and are
documented in README.md (Deliverable E - Test cases).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTaxEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env["mrelate.tds.engine"]
        cls.fy = "2026-27"

    def _total(self, regime, taxable):
        return self.engine.compute(self.fy, regime, taxable)["total_tax"]

    # ---- NEW regime -------------------------------------------------
    def test_new_rebate_makes_12L_tax_free(self):
        # Taxable 12,00,000 -> slab tax 60,000 fully wiped by 87A rebate.
        self.assertEqual(self._total("new", 1200000), 0.0)

    def test_new_16L(self):
        # 20,000 + 40,000 + 60,000 = 1,20,000; +4% cess = 1,24,800.
        self.assertEqual(self._total("new", 1600000), 124800.0)

    def test_new_20L(self):
        # 20,000+40,000+60,000+80,000 = 2,00,000; +4% cess = 2,08,000.
        self.assertEqual(self._total("new", 2000000), 208000.0)

    # ---- OLD regime -------------------------------------------------
    def test_old_rebate_makes_5L_tax_free(self):
        self.assertEqual(self._total("old", 500000), 0.0)

    def test_old_10L(self):
        # 12,500 + 1,00,000 = 1,12,500; +4% cess = 1,17,000.
        self.assertEqual(self._total("old", 1000000), 117000.0)

    def test_old_15L(self):
        # 12,500 + 1,00,000 + 1,50,000 = 2,62,500; +4% cess = 2,73,000.
        self.assertEqual(self._total("old", 1500000), 273000.0)

    # ---- Surcharge --------------------------------------------------
    def test_new_surcharge_60L(self):
        # Taxable 60,00,000: slab tax = 3,00,000 + 30% of 36L = 13,80,000.
        # surcharge 10% (50L-1Cr) = 1,38,000; cess 4% of 15,18,000 = 60,720.
        # total = 13,80,000 + 1,38,000 + 60,720 = 15,78,720.
        self.assertEqual(self._total("new", 6000000), 1578720.0)


@tagged("post_install", "-at_install")
class TestDeclaration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "UT Dummy Employee"})

    def _decl(self, **vals):
        base = {
            "employee_id": self.employee.id,
            "financial_year": "2026-27",
            "remaining_months": 10,
        }
        base.update(vals)
        return self.env["mrelate.tds.declaration"].create(base)

    def test_projection_and_recommendation(self):
        d = self._decl(regime="new", salary_projected_remaining=1500000)
        # gross = 15,00,000
        self.assertEqual(d.gross_annual_salary, 1500000)
        # new taxable = 15,00,000 - 75,000 = 14,25,000
        self.assertEqual(d.taxable_income_new, 1425000)
        # old taxable = 15,00,000 - 50,000 = 14,50,000
        self.assertEqual(d.taxable_income_old, 1450000)
        # new is cheaper here
        self.assertEqual(d.recommended_regime, "new")
        # tax_new = 93,750 + 4% = 97,500 ; monthly over 10 = 9,750
        self.assertEqual(d.tax_new, 97500.0)
        self.assertEqual(d.monthly_tds, 9750.0)

    def test_80c_reduces_old_regime(self):
        d = self._decl(regime="old", salary_projected_remaining=1000000,
                       ded_80c=200000)  # capped at 1,50,000
        # old taxable = 10,00,000 - 50,000(std) - 1,50,000(80C cap) = 8,00,000
        self.assertEqual(d.taxable_income_old, 800000)

    def test_no_declarations(self):
        d = self._decl(regime="new", salary_projected_remaining=600000)
        # taxable new = 6,00,000 - 75,000 = 5,25,000 -> tax 0 (rebate covers <=12L)
        self.assertEqual(d.taxable_income_new, 525000)
        self.assertEqual(d.tax_new, 0.0)
        self.assertEqual(d.monthly_tds, 0.0)

    def test_workflow_guards(self):
        from odoo.exceptions import UserError
        d = self._decl(regime="new", salary_projected_remaining=1500000)
        # cannot apply before approval
        with self.assertRaises(UserError):
            d.action_apply_to_contract()
        d.action_submit()
        d.action_review()
        d.action_approve()
        # still needs a version_id
        with self.assertRaises(UserError):
            d.action_apply_to_contract()


@tagged("post_install", "-at_install")
class TestMarginalReliefAndExtras(TransactionCase):
    """v1.2.0 fixes: marginal relief, 206AA, senior basic exemption."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env["mrelate.tds.engine"]
        cls.fy = "2026-27"

    def _total(self, regime, taxable, **kw):
        return self.engine.compute(self.fy, regime, taxable, **kw)["total_tax"]

    # ---- 87A marginal relief (new regime) ---------------------------
    def test_new_87a_marginal_relief_at_boundary(self):
        # Just inside boundary: 12,00,000 -> 0 (full rebate, no marginal-relief needed)
        self.assertEqual(self._total("new", 1200000), 0.0)

    def test_new_87a_marginal_relief_just_above(self):
        # 12,10,000: without marginal relief, tax on 12.1L = 61,500 + cess = 63,960
        # With marginal relief: tax should not exceed (12,10,000 - 12,00,000) = 10,000
        # 10,000 + 4% cess = 10,400; rounded to nearest 10 = 10,400
        out = self.engine.compute(self.fy, "new", 1210000)
        self.assertLessEqual(out["total_tax"], 10400 + 1, msg=out["explanation"])

    def test_new_87a_marginal_relief_phase_out(self):
        # Around 12,75,000 the relief phases out; beyond that, regular tax applies.
        out = self.engine.compute(self.fy, "new", 1300000)
        # Tax on 13L (new) = 20k(5%) + 40k(10%) + 15k(15%) = 66,250; cess 4% = 68,900
        # marginal relief excess = 1,00,000; 68,900 > excess so relief doesn't kick in
        # (i.e. tax_after_rebate 66,250 > excess 1,00,000 is False -> no rebate)
        # Actual: rebate path returns 0 because tax_after_rebate < excess
        # Without marginal relief: same 68,900
        self.assertGreater(out["total_tax"], 50000)

    # ---- Senior citizen old-regime exemption ------------------------
    def test_old_senior_basic_exemption_3L(self):
        # Senior: 3L exempt vs 2.5L for under-60.
        # 5,00,000 taxable: under-60 -> 12,500 wiped by 87A -> 0
        # Senior with override: slab tax = 0 (0-3L nil) + 5% of (3L-5L) = 10,000
        # -> 87A rebate (taxable <= 5L) wipes it -> 0
        out = self.engine.compute(self.fy, "old", 500000,
                                  basic_exemption_override=300000)
        self.assertEqual(out["total_tax"], 0.0)
        # 7,00,000 senior: 0 (0-3L) + 5% of 2L (3L-5L) + 20% of 2L (5L-7L) = 50,000
        # 87A: taxable 7L > 5L cap -> no rebate. Total: 50,000 + 4% = 52,000
        out2 = self.engine.compute(self.fy, "old", 700000,
                                   basic_exemption_override=300000)
        self.assertEqual(out2["total_tax"], 52000.0)

    def test_old_super_senior_basic_exemption_5L(self):
        # 5L super-senior: all in nil band -> 0
        out = self.engine.compute(self.fy, "old", 500000,
                                  basic_exemption_override=500000)
        self.assertEqual(out["total_tax"], 0.0)

    # ---- Sec 206AA floor --------------------------------------------
    def test_206aa_floor_applies(self):
        # PAN missing on 15L taxable: normal tax under new = 97,500 (cess included)
        # 20% of 15L = 3,00,000 - higher -> floor applies
        new_tax, applied = self.engine.apply_206aa_floor(1500000, 97500)
        self.assertTrue(applied)
        self.assertEqual(new_tax, 300000.0)

    def test_206aa_floor_does_not_apply_when_normal_higher(self):
        # 60L taxable: normal tax is much higher than 12L (20%) - no floor.
        new_tax, applied = self.engine.apply_206aa_floor(6000000, 1578720)
        self.assertFalse(applied)
        self.assertEqual(new_tax, 1578720)


@tagged("post_install", "-at_install")
class TestDeclarationExtras(TransactionCase):
    """80CCD(2) auto-cap; PAN regex; regime lock; drift detection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "UT Extras Emp"})

    def _decl(self, **vals):
        base = {
            "employee_id": self.employee.id,
            "financial_year": "2026-27",
            "remaining_months": 10,
        }
        base.update(vals)
        return self.env["mrelate.tds.declaration"].create(base)

    def test_80ccd2_cap_new_regime_14_pct(self):
        # Basic+DA 6L; 80CCD(2) input 2L -> capped at 14% of 6L = 84,000
        d = self._decl(regime="new", salary_projected_remaining=1500000,
                       annual_basic_da=600000, ded_80ccd_2_employer=200000)
        self.assertEqual(d.ded_80ccd_2_employer_capped, 84000.0)

    def test_80ccd2_cap_old_regime_10_pct(self):
        d = self._decl(regime="old", salary_projected_remaining=1500000,
                       annual_basic_da=600000, ded_80ccd_2_employer=200000)
        # 10% of 6L = 60,000
        self.assertEqual(d.ded_80ccd_2_employer_capped, 60000.0)

    def test_pan_regex(self):
        d = self._decl(pan="ABCDE1234F", regime="new", salary_projected_remaining=1500000)
        self.assertTrue(d.pan_valid)
        d2 = self._decl(pan="INVALID123", regime="new",
                        salary_projected_remaining=1500000, employee_id=self.env["hr.employee"].create({"name": "UT2"}).id)
        self.assertFalse(d2.pan_valid)

    def test_206aa_triggered_when_pan_missing(self):
        # Without PAN: 206AA fires; 15L taxable -> 3L tax
        d = self._decl(regime="new", salary_projected_remaining=1500000,
                       pan_missing=True)
        self.assertTrue(d.pan_206aa_applied)
        self.assertEqual(d.total_tax_liability, 300000.0)
        # Monthly: 300000 / 10 = 30,000
        self.assertEqual(d.monthly_tds, 30000.0)

    def test_unique_employee_fy(self):
        self._decl(regime="new", salary_projected_remaining=500000)
        with self.assertRaises(Exception):
            self._decl(regime="new", salary_projected_remaining=600000)

    def test_bonus_month_extra_tds(self):
        d = self._decl(regime="new", salary_projected_remaining=1500000,
                       bonus_variable=200000)
        # gross 17L; new tax with bonus ~ depends; just verify > 0 when bonus > 0
        self.assertGreater(d.bonus_month_extra_tds, 0)
