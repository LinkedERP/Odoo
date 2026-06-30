# Mrelate India Payroll TDS & Income-Tax Declaration (Odoo 19)

A custom, **isolated** module that adds a real Indian income-tax declaration and
**monthly TDS** calculation on top of standard Odoo India payroll. It does **not**
edit any standard `l10n_in_hr_payroll` salary rule. On approval it writes the
computed monthly TDS into the existing `hr.version.l10n_in_tds` field, which the
standard payslip rule already deducts.

- **Target year:** FY 2026-27 (AY 2027-28). Rates are data-driven (see below).
- **Scope:** Phase 1 MVP. Phase 2 items are listed under *Known limitations*.
- **Safety:** never computes/validates/posts a payslip, never creates accounting.

---

## A. Research summary & official sources
FY 2026-27 slabs/rebate/surcharge are unchanged from FY 2025-26 (Budget 2026 made
no change). Figures seeded in `data/tds_fy_2026_27_data.xml`:

| | New regime (115BAC) | Old regime |
|---|---|---|
| Slabs | 0–4L nil, 4–8L 5%, 8–12L 10%, 12–16L 15%, 16–20L 20%, 20–24L 25%, >24L 30% | 0–2.5L nil, 2.5–5L 5%, 5–10L 20%, >10L 30% |
| Standard deduction | ₹75,000 | ₹50,000 |
| 87A rebate | taxable ≤ ₹12L → up to ₹60,000 | taxable ≤ ₹5L → up to ₹12,500 |
| Surcharge | 50L–1Cr 10%, 1–2Cr 15%, >2Cr 25% (capped) | +2–5Cr 25%, >5Cr 37% |
| Cess | 4% | 4% |

Sources:
- Income Tax Dept — Salaried Individuals AY 2026-27:
  https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1
- Tax Rates: https://www.incometaxindia.gov.in/tax-rates
- Old vs New calculator: https://www.incometaxindia.gov.in/tax-calculator-old-regime-vs-new-regime

## B. Functional design
1. **Declaration** (`mrelate.tds.declaration`): one record per employee per FY.
   Captures regime, PAN/PAN-missing, salary projection, previous-employer income
   & TDS, other/interest/house-property income, and old-regime deductions
   (HRA, LTA, 80C, 80CCD(1B), 80CCD(2), 80D, home-loan interest, other).
2. **Engine** computes tax under **both** regimes, recommends the cheaper one,
   and shows a side-by-side breakdown.
3. **Monthly TDS** = (chosen-regime tax − previous-employer TDS − TDS already
   deducted this FY) ÷ remaining months, rounded to nearest ₹10.
4. **Workflow:** Draft → Submitted → Reviewed → Approved → Locked (+ Cancel).
   Employees edit their own draft; reviewers (payroll) review/approve/lock.
5. **Apply to contract:** a reviewer button writes `monthly_tds` to
   `hr.version.l10n_in_tds`. Payslip then deducts it on next (draft) compute.
6. **Audit:** `mail.thread` tracks regime, state, amounts and posts a chatter
   note whenever TDS is applied to a contract.

## C. Technical design
```
mrelate_payroll_tds/
├── __manifest__.py            depends: mail, hr_payroll, l10n_in_hr_payroll
├── models/
│   ├── tds_year_config.py      mrelate.tds.year.config + .slab + .surcharge.band
│   ├── tax_engine.py           mrelate.tds.engine (AbstractModel, stateless)
│   └── tds_declaration.py      mrelate.tds.declaration (+ workflow, write-back)
├── security/                   privilege + 2 groups + record rules + ACL csv
├── data/                       FY 2026-27 rates (configurable records)
├── views/                      declaration, config, menus
└── tests/                      engine + declaration unit tests
```
- **Data-driven rates:** all statutory numbers live in records. A new FY = new
  `mrelate.tds.year.config` rows; **no code change**.
- **Odoo 19 specifics handled:** uses `hr.version` (not `hr.contract`) for the
  TDS field; uses the new `res.groups.privilege` security model (the old
  `res.groups.category_id` was removed in 19); views use `<list>` and `<chatter/>`.

## D. Implementation
See the source. Build is complete for Phase 1.

## E. Test cases & expected results
Unit tests in `tests/test_tax_engine.py` (hand-derived from official slabs):

| Case | Regime | Taxable | Expected total tax |
|------|--------|---------|--------------------|
| 12L rebate | new | 12,00,000 | 0 |
| 16L | new | 16,00,000 | 1,24,800 |
| 20L | new | 20,00,000 | 2,08,000 |
| 60L + surcharge | new | 60,00,000 | 15,78,720 |
| 5L rebate | old | 5,00,000 | 0 |
| 10L | old | 10,00,000 | 1,17,000 |
| 15L | old | 15,00,000 | 2,73,000 |

Declaration tests: projection→recommendation (new cheaper at 15L gross, monthly
TDS ₹9,750 over 10 months), 80C cap reduces old-regime taxable, no-declaration
zero-tax case, and workflow guards (cannot apply before approval / without a
version). **UAT scenarios** (Deliverable F) are in `DEPLOY_AND_UAT.md`.

## G. Known limitations (Phase 1)
- **Marginal relief not applied** at the 87A boundary (new regime, income just
  over ₹12L) nor at surcharge thresholds — can over-state tax near boundaries.
- **Perquisites** (sec 17(2)) not modelled — Phase 2.
- **HRA exemption** uses the least-of-three approximation from annual figures
  (not month-wise); metro = simple 50% vs 40%.
- **80CCD(2)** entered as-is; the 10%/14%-of-salary cap is **not** auto-enforced.
- **Age-based** old-regime exemption (senior/super-senior) not handled (assumes <60).
- **Sec 206AA** higher TDS for missing PAN is flagged, not auto-applied.
- Spreading uses a flat remaining-months divisor, not a strict sec-192 average rate.

## H. Items requiring CA / payroll validation
1. Marginal relief (rebate & surcharge boundaries).
2. HRA least-of-three formula & metro classification.
3. 80CCD(2) deductible limit per regime.
4. House-property loss set-off cap (₹2,00,000) edge cases.
5. Rounding (sec 288A/288B) expectations.
6. Sec-192 averaging method for monthly TDS.
7. Treatment of previous-employer income/TDS in projection.
8. Whether surcharge band should use taxable income vs total income.

## I. Rollback plan
The module is fully isolated; rollback is clean:
1. **Before install:** nothing in Odoo changed (only local files exist).
2. **To remove after install:** Apps → *Mrelate India Payroll TDS* → **Uninstall**.
   This drops the module's models/records/menus. It does **not** revert any
   `l10n_in_tds` value already written — see step 3.
3. **To revert an applied TDS value:** set `hr.version.l10n_in_tds` back to its
   previous figure (record the old value before applying; UAT uses the dummy only).
4. No standard rules are modified, so there is nothing else to undo.

## J. Management summary
A self-contained Odoo 19 module that turns the current "store a number in
`l10n_in_tds`" setup into a proper employee tax-declaration + dual-regime
(old/new) monthly-TDS engine for FY 2026-27, with approval workflow, audit trail,
old-vs-new comparison and a transparent calculation breakdown. Tax rates are
configurable data (future years need no code). It integrates by writing the
approved monthly TDS into the existing standard field — no standard payroll rule
is touched, no payslip is posted, and no accounting is created. Several legal
edge-cases are deliberately deferred to Phase 2 and flagged for CA validation.
