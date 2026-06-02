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
