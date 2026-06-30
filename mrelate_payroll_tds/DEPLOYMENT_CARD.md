# Deployment & Rollback Card — mrelate_payroll_tds (Odoo 19, DEV)

Keep this open while you push & install. Short and practical.

---

## A. What this module DOES
- Adds an employee **tax declaration** (regime, PAN, income, deductions) per FY.
- Computes tax under **both** old & new regimes (FY 2026-27) and recommends the cheaper.
- Spreads remaining tax into a **monthly TDS** figure.
- On approval, **writes that figure to the standard `hr.version.l10n_in_tds`** field.
- Keeps an approval workflow + audit trail; rates are configurable data.

## B. What this module does NOT do
- Does **not** compute, validate, or **post** any payslip.
- Does **not** create any **accounting / journal** entry.
- Does **not** edit standard Odoo India payroll rules.
- Does **not** handle perquisites, marginal relief, age-based exemption, or PAN-missing
  extra TDS (Phase 2 / flagged for CA validation).

## C. Deploy to Odoo.sh DEV
1. Unzip so `mrelate_payroll_tds/` sits in your addons path.
2. `git add mrelate_payroll_tds`
3. `git commit -m "Add mrelate_payroll_tds (Phase 1: India TDS)"`
4. `git push origin 19.0`
5. Wait for the Odoo.sh **dev branch build to go green**.

## D. Install in Apps
1. Open the **DEV** database as admin (turn on Developer Mode).
2. **Apps → Update Apps List**.
3. Search **"Mrelate India Payroll TDS" → Install**.
4. **Settings → Users & Companies → Groups →** add yourself to **"TDS: Payroll Reviewer"**.

## E. If the Odoo.sh BUILD fails
- Open the build log on Odoo.sh; read the **last red lines**.
- Common cause: a dependency not in the branch. This module needs **`hr_payroll`**
  and **`l10n_in_hr_payroll`** — confirm both are installed/available on the branch.
- Fix locally, commit, push again. The DB is not changed until a build succeeds.

## F. If the APP INSTALL fails
- Odoo shows a red error dialog — **copy the full text**.
- Nothing is half-installed: a failed install **rolls itself back**. Fix and retry.
- If unsure, paste the error to Claude — most install errors map to section G.

## G. Most likely install errors + exact fix
| Error mentions | Fix |
|---|---|
| `External ID not found: hr_payroll.menu_hr_payroll_root` | In `views/tds_menus.xml`, on the first `<menuitem id="menu_tds_root">` change `parent="hr_payroll.menu_hr_payroll_root"` to another existing menu, or **delete the `parent=` attribute** (menu becomes top-level). Reinstall. |
| `Invalid field 'category_id'` on `res.groups.privilege` | In `security/tds_security.xml`, delete the line `<field name="category_id" ref="module_category_mrelate_tds"/>` inside the `privilege_mrelate_tds` record (cosmetic only). Reinstall. |
| `group ... not found` / ACL or `Invalid model ... in ir.model.access` | Confirm `security/tds_security.xml` is listed **before** `security/ir.model.access.csv` in `__manifest__.py` (it is). Group IDs in the CSV must be `group_tds_employee` / `group_tds_reviewer`. |
| XML view error (`Field ... does not exist` / parse error) | Note the file + line in the error. Usually a field-name typo in a `views/*.xml`. Fix that one line and reinstall. Paste it to Claude if unclear. |

## H. Rollback
1. **If installed:** Apps → *Mrelate India Payroll TDS* → **Uninstall** (drops its
   models, records, menus). The module is isolated, so nothing standard is affected.
2. **Revert any applied TDS value:** if you clicked *Apply Monthly TDS to Contract*,
   set that `hr.version.l10n_in_tds` back to its prior number (note it down first;
   UAT uses the **dummy** only, so impact is contained).
3. **Remove from branch:** delete the `mrelate_payroll_tds/` folder, commit, push; OR
   `git revert <commit-hash>` of the "Add mrelate_payroll_tds" commit, then push.
4. **Confirm clean state:** no payslip was posted and no journal entry was created
   (this module never does either). Check Payroll → Payslips show **Draft**; Accounting
   has **no new entries** from this work.

## I. What NOT to do
- ❌ Do **not** test on **real employees** first — use **TEST Payroll Dummy** only.
- ❌ Do **not** validate/**post** payslips during testing.
- ❌ Do **not** use this for **real payroll** until a **CA / payroll expert validates**
  the tax rules (marginal relief, surcharge, perquisites, deductions caps).
- ❌ Do **not** change company-wide payroll settings or standard localization rules.

## J. UAT entry checklist (after a successful install)
- [ ] Build green on Odoo.sh DEV.
- [ ] App shows **Installed**.
- [ ] You are in group **TDS: Payroll Reviewer**.
- [ ] **Payroll → India TDS → Configuration → TDS Tax Configuration** shows **two**
      FY 2026-27 rows (New + Old) with correct slabs.
- [ ] Menu **Payroll → India TDS → Tax Declarations** opens.
- [ ] You have the **TEST Payroll Dummy** employee + its contract version ready.
- [ ] Then ping Claude → run the 8 UAT scenarios in `DEPLOY_AND_UAT.md` (dummy only).
