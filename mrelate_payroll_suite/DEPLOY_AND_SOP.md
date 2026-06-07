# Deploy + SOP — India Payroll Suite

> Audience: Mrelate HR + LinkedERP partner-consultants. Bookmark this page.

## Part A — Deploy (one-time, dev branch first)

1. From your repo's working folder:
   ```
   git status                # confirm clean
   git checkout 19.0         # the dev branch
   git pull
   ```
2. Make sure these THREE folders sit at the top of your `addons` path:
   - `mrelate_payroll_tds/`           (v19.0.1.2.0 — patched)
   - `mrelate_payroll_expense_integration/`
   - `mrelate_payroll_suite/`         (NEW)
3. Commit + push:
   ```
   git add mrelate_payroll_tds mrelate_payroll_expense_integration mrelate_payroll_suite
   git commit -m "India Payroll Suite v1.0 — TDS fixes + dashboards + monthly run wizard"
   git push origin 19.0
   ```
4. Watch Odoo.sh build the dev branch. **Wait for green.**
5. In the rebuilt DB (Mrelate dev): **Apps → Update Apps List**.
6. Search **India Payroll Suite** → **Install**. (Will pull the other two as dependencies if not already installed; otherwise click each module's *Upgrade* button.)
7. After install, run unit tests once:
   ```
   odoo --test-tags /mrelate_payroll_tds --stop-after-init
   ```
   Should pass 11 tests (engine + declaration + v1.2.0 fixes).
8. Confirm yourself is in group **TDS: Payroll Reviewer** (Settings → Users → your record → Other Info).
9. **Verify the dashboards menu:** Payroll → India TDS → you should see *Monthly Payroll Run*, *Tax Declarations*, *TDS Dashboard*, *Payroll Cost Dashboard*, *Configuration*.

## Part B — Production cut-over (when customer is ready)

> Do this AFTER UAT on dev is signed off (Part D).

For each company (start with Mrelate):

1. **State and PT registration** — confirm:
   - Company state set correctly on `res.company` (Mrelate = Karnataka).
   - Customer has the right PTRC / PTEC registration for that state.
2. **Set the PT rule parameter on every employee version** — one bulk update via Settings → Technical → DB Manager or via the Server Actions module. Reference IDs:
   - Karnataka: `l10n_in_pt_ka`
   - Maharashtra (male): `l10n_in_pt_male_mh`
   - Gujarat: `l10n_in_pt_gj`
   - West Bengal: `l10n_in_pt_wb`
   - Andhra Pradesh: `l10n_in_pt_ap`
3. **LWF** — `l10n_in_labour_welfare` is a non-stored computed boolean in standard l10n_in_hr_payroll. Verify the standard module's compute correctly picks up your company state. If not (Mrelate KA: LWF is annual not half-yearly; standard might be MH-biased), file separately.
4. **Real employee versions** — for the 35 employees currently with wage=0:
   - Get an HR-confirmed CTC sheet (basic % / HRA / allowances / regime preference / PAN / DOB).
   - Bulk-update via the wizard you have, or the CSV importer at Settings → Technical → Import.
5. **Run Monthly Payroll Run** in dry-run mode (don't validate payslips yet) for the current month. Compare TDS per employee against your manual calc / current Tally setup. Sign off.
6. Switch off Tally/external payroll. Validate the Odoo payslips. Generate Form 16 at FY end (use the IT portal Form 16 utility for now — the standard Odoo l10n_in_hr_payroll Form 16 has stale rates).

## Part C — Monthly HR cycle (after cut-over)

> Time per month: ~15 min for HR + 15 min for finance review. Compared to ~4 hours manual.

**Around the 25th of each month:**

1. Collect declaration changes (regime switch attempts, new investments, joining bonuses, etc.) — push them into employees' declarations.
2. Approve all newly submitted declarations.

**On the last working day of the month:**

3. Payroll → India TDS → **Monthly Payroll Run**.
4. Set period start = 1st of this month, period end = last of this month. Click **Run**.
5. Review the log — fix anything flagged.
6. Open *Payroll → Payslips* → filter "Draft, this month". Spot-check 3-4 random employees against expectations. Specifically check:
   - Gross matches contract version wage.
   - PF deducted (₹1,800 capped).
   - PT deducted (per state).
   - TDS deducted matches the declaration's `monthly_tds`.
   - Expenses pulled in (if any were approved this month).
7. Click **Validate** on each (or bulk via list view → Action → Validate Payslips).
8. Finance pays via NEFT/RTGS, references the payslip number.
9. TDS deposit: 7th of next month (the standard Odoo TDS challan / Form 24Q export is a follow-up step — for now: pull the total TDS from the Payroll Cost Dashboard, file the challan via NSDL).
10. Quarterly: Form 24Q via standard `l10n_in_hr_payroll` or NSDL utility.

## Part D — UAT scenarios (8) on dev

For each row: create the situation on the **ZZ_UAT_*** test employees (DEV only, never on real employees). Document Pass/Fail in your spreadsheet.

| # | Scenario | Employee | Expected | Cross-check |
|---|---|---|---|---|
| 1 | New regime, salary under rebate | T1 (₹40k/mo) | Decl shows tax_new=0, monthly_tds=0; payslip TDS=0 | ✅ Already validated by author |
| 2 | New regime, salary AT rebate ceiling | T2 (₹100k/mo, ₹12L) | tax_new=0, monthly_tds=0 (rebate covers) | ✅ Already validated |
| 3 | New regime, mid TDS | T3 (₹175k/mo, ₹21L) | tax_new=2,14,500, monthly=21,450 | ✅ Already validated |
| 4 | New regime, surcharge band | T4 (₹500k/mo, ₹60L) | tax_new=15,52,980, monthly=1,55,300 | ✅ Already validated |
| 5 | **Marginal relief at 12L boundary (POST-DEPLOY ONLY)** | T2 modified to gross=12,50,000 | tax_new ≤ ~52,000 (NOT ~94,200) | Requires deploy of patched engine |
| 6 | **Sec 206AA: PAN missing** | T3 with `pan_missing=True` | total_tax = max(normal, 20% × taxable). For T3: max(2.14L, 20%×20.25L=4.05L) → 4.05L floor | Requires deploy |
| 7 | **Senior citizen old regime** | T2 with `age_category='senior'`, regime='old' | Slabs use 3L nil basic instead of 2.5L | Requires deploy |
| 8 | **Regime lock after apply** | T3 already applied; try switching regime to 'old' | Form shows warning popup; field is readonly | Requires deploy |

Scenarios 1–4 are **already validated** with the live (pre-patch) engine.
Scenarios 5–8 validate the v1.2.0 patches — run after deploy.

## Part E — What's already done on the dev DB

The author of this audit (Claude/Akshay session of 7 June 2026) has executed:

- ✅ TDS rule on Mrelate's struct 9 (`Mrelate: Regular Pay`) overridden to **cap TDS at GROSS** so payslips can never go negative. Live now.
- ✅ Reset of `hr.version` 141 (TEST Payroll Dummy) `l10n_in_tds` from drifted ₹32,540 → ₹9,750 (the value last applied by decl 3).
- ✅ Deletion of broken draft slip 8 (was net = −₹11,290) and orphan slip 24 (gross=0).
- ✅ Created 4 UAT test employees (IDs 438–441, names start with `ZZ_UAT_`) with diverse salary tiers + April + May + June payslips in DRAFT.
- ✅ Created TDS declarations (IDs 7–10) for the 4 test employees, all approved + applied to versions.
- ✅ Wired Karnataka PT (`l10n_in_pt_ka`) to all UAT versions + the TEST Dummy.
- ⚠️ Real employees (35 of 36 in Mrelate) still have wage=0. **Not touched per user instruction.**
- ⚠️ Declaration 6 (Prathuk Hedge real employee, gross=0, state=draft) is sitting in the workflow. Notify the employee or cancel.

## Part F — Known limitations + roadmap

- Form 12BB report is a "Form 12BB-style" printout — useful internally, but isn't the IT-portal-prescribed PDF. For the official PDF, use the IT portal utility.
- Form 16 Part B: use IT portal (or wait for v1.1 wrapper).
- LWF auto-deduction: relies on standard l10n_in_hr_payroll's state-driven compute; verify per state.
- ESI: not automated (most Mrelate employees are above ₹21k — out of net). For an employee dropping below ₹21k, manually toggle `l10n_in_esic=True` on their version.
- Sec 89(1) arrears relief, perquisite valuation (sec 17(2)), one-time-switch-back rule for business income: out of scope for v1.0.

## Part G — Rollback

Each module uninstalls cleanly:
1. Apps → uninstall **India Payroll Suite** (drops dashboards, wizard, report).
2. Apps → uninstall **India Payroll TDS** (drops declarations, configs).
3. Apps → uninstall **Mrelate Payroll Expense Integration** (drops the *Refresh Expenses* button override).

The standard `l10n_in_hr_payroll` is untouched throughout — no rollback needed there.

The custom override on the **TDS salary rule** (struct 9 rule id 166, cap at gross) is NOT removed by uninstall — that's a live config change. To revert, edit the rule and set the python compute back to `result = -(version.l10n_in_tds)` (but you'd then lose the safety cap; not recommended).
