# Implementation Log — mrelate_payroll_tds (India TDS / Income-Tax Declaration)

> Custom Odoo 19 module. DEV-only build. Author: Claude (Claude Code) for Akshay / LinkedERP.
> Started: 2026-06-02. Target FY: **2026-27 (AY 2027-28)**. Scope: **Phase 1 MVP**.

## Capability boundary (read first)
- This module's **source is authored locally** in `C:\Users\AkshayJain\odoo-mcp-server\mrelate_payroll_tds\`.
- Claude **cannot install/upgrade** the module into the Odoo dev DB (no such MCP tool) and
  **cannot create records in the new models** over MCP (not whitelisted). Therefore:
  - Deliverables A–E, G–J are produced by Claude.
  - Deliverable F (live DEV test evidence) requires **you to deploy + install** on branch `19.0`,
    after which Claude can help drive UAT and verify with read tools + the narrow `l10n_in_tds` write.

## Decisions (confirmed by user 2026-06-02)
1. Financial year: **FY 2026-27 (AY 2027-28)**. Rates stored as configurable data (future years = data only).
2. Build scope: **Phased MVP first** (regime + core declarations + dual engine + approval + write-back + UAT).
3. Source location: **new folder in this workspace** for you to push to Odoo.sh.

## Official sources used (Deliverable A)
- Income Tax Dept — Salaried Individuals AY 2026-27 (slabs/rebate/surcharge/cess):
  https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1
- Income Tax Dept — Tax Rates: https://www.incometaxindia.gov.in/tax-rates
- Old vs New regime calculator: https://www.incometaxindia.gov.in/tax-calculator-old-regime-vs-new-regime
- Budget 2026 / FY 2026-27: no slab/rebate/surcharge change vs FY 2025-26 (Finance Act 2025) — confirmed via search of pib.gov.in / incometax.gov.in result set 2026-06-02.

## Rate facts seeded (FY 2026-27)
NEW (115BAC): 0-4L nil; 4-8L 5%; 8-12L 10%; 12-16L 15%; 16-20L 20%; 20-24L 25%; >24L 30%.
  Std deduction 75,000. 87A: taxable<=12,00,000 -> rebate up to 60,000. Surcharge 50L-1Cr 10%,
  1-2Cr 15%, >2Cr 25% (capped). Cess 4%.
OLD: 0-2.5L nil; 2.5-5L 5%; 5-10L 20%; >10L 30%. Std deduction 50,000.
  87A: taxable<=5,00,000 -> rebate up to 12,500. Surcharge 50L-1Cr 10%, 1-2Cr 15%, 2-5Cr 25%,
  >5Cr 37%. Cess 4%.

## Items flagged "requires CA / payroll validation" (Deliverable H)
- Marginal relief at the 87A rebate boundary (new regime, income just over 12L) — NOT yet implemented; flagged.
- Surcharge marginal relief at 50L / 1Cr / 2Cr / 5Cr boundaries — NOT yet implemented; flagged.
- HRA exemption least-of-three formula and metro/non-metro % — implemented as approximation; validate.
- 80CCD(2) employer-NPS deductible limit (10% vs 14% of salary) — entered as-is, no cap enforced; validate.
- House-property loss set-off cap (Rs 2,00,000) — implemented as cap; validate edge cases.
- Senior / super-senior basic exemption (old regime) — MVP assumes age < 60; flagged.
- Rounding under sec 288A/288B (nearest Rs 10) — applied to final figures; validate.
- Sec 192 average-rate TDS spreading over remaining months — implemented simply; validate.

## File-by-file change log
| Date | File | Action | Notes |
|------|------|--------|-------|
| 2026-06-02 | IMPLEMENTATION_LOG.md | create | this log |
| 2026-06-02 | __init__.py, __manifest__.py | create | module backbone |
| 2026-06-02 | models/tds_year_config.py | create | configurable rates: year config + slabs + surcharge bands |
| 2026-06-02 | models/tax_engine.py | create | dual-regime calculation service (AbstractModel) |
| 2026-06-02 | models/tds_declaration.py | create | main declaration model + workflow + write-back |
| 2026-06-02 | security/tds_security.xml | create | Odoo-19 privilege + 2 groups + 2 record rules |
| 2026-06-02 | security/ir.model.access.csv | create | ACLs for 4 models x 2 groups |
| 2026-06-02 | data/tds_fy_2026_27_data.xml | create | FY 2026-27 new+old configs, slabs, surcharge bands |
| 2026-06-02 | views/tds_declaration_views.xml | create | form/list/search + action |
| 2026-06-02 | views/tds_config_views.xml | create | config form/list + action |
| 2026-06-02 | views/tds_menus.xml | create | menus under Payroll root |
| 2026-06-02 | tests/test_tax_engine.py | create | 7 engine + 4 declaration unit tests |
| 2026-06-02 | README.md | create | deliverables A,B,C,E,G,H,I,J |
| 2026-06-02 | DEPLOY_AND_UAT.md | create | deploy steps + 8 UAT scenarios (Deliverable F plan) |

## Live DB facts discovered during build (read-only MCP)
- Odoo 19 `res.groups` has **no** `category_id`; uses `privilege_id` ->
  `res.groups.privilege`. Security XML written accordingly.
- `country_code` exists on `hr.version` (computed char) — earlier TDS-button finding.
- Read allowlist excludes `ir.ui.menu` / `ir.model.data`, so the menu/group external
  IDs could not be introspected; `hr_payroll.menu_hr_payroll_root` left as the single
  documented deploy-check (see DEPLOY_AND_UAT.md Step 2).

## Pre-deployment self-review (2026-06-02)
- FIX: `mrelate.tds.declaration` overrode the built-in `display_name` field with a
  custom compute + `_rec_name='display_name'` (fragile in Odoo 16+). Replaced with a
  normal `name` field (`_compute_name`, `_rec_name='name'`); updated form title.
- Verified: manifest data-load order (security -> data -> views) correct; all 6
  referenced data files exist; no legacy `<tree>`/`attrs=`/`states=`; ACL model &
  group IDs resolve; record rules reference `model_mrelate_tds_declaration`.
- Residual (documented) risks: external IDs `hr_payroll.menu_hr_payroll_root` and the
  `res.groups.privilege.category_id` field could not be introspected over MCP.
- Packaged: mrelate_payroll_tds.zip (top-level folder, 17 files).

## Records created in DEV
(none yet — module not installed; see capability boundary)

## Test results
Unit tests authored (11 total). They run on the dev/test DB AFTER deployment via
`--test-enable` / `--test-tags /mrelate_payroll_tds`. Live UAT = Deliverable F,
executed jointly per DEPLOY_AND_UAT.md once you install.
