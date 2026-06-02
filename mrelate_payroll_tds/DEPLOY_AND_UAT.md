# Deploy & UAT guide — mrelate_payroll_tds

Written click-by-click. **I (Claude) cannot install the module for you** — I have no
tool to deploy code or upgrade apps on your Odoo dev server. You do steps 1–4;
then we do UAT (step 5) together and I verify with read tools.

---

## Step 1 — Put the module on your Odoo.sh 19.0 branch
1. Copy the whole folder `mrelate_payroll_tds/` into your Odoo.sh repository's
   addons path (the same folder that holds your other custom modules).
2. Commit and push to the **development** branch `19.0`.
   ```
   git add mrelate_payroll_tds
   git commit -m "Add mrelate_payroll_tds (Phase 1: India TDS declaration + engine)"
   git push origin 19.0
   ```
3. Odoo.sh will rebuild the dev branch. Wait for the build to go green.

> If you don't use Odoo.sh git and instead upload modules manually, drop the
> folder into your addons directory and restart the Odoo service.

## Step 2 — Install the module
1. Log in to the **DEV** database as an administrator.
2. **Apps** → *Update Apps List* (you may need developer mode on).
3. Search **"Mrelate India Payroll TDS"** → **Install**.

### ⚠️ One deploy-check
The menu is placed under the standard Payroll root menu
(`hr_payroll.menu_hr_payroll_root`). This is the standard Odoo ID and should
resolve because the module depends on `hr_payroll`. **If** install errors on that
external ID, open `views/tds_menus.xml` and change the first `<menuitem>` `parent`
to another existing menu (or remove `parent` to make it a top-level menu), then
reinstall. Tell me and I'll adjust the file.

## Step 3 — Give yourself the rights
1. Developer mode → **Settings → Users & Companies → Groups**.
2. Find **"TDS: Payroll Reviewer"**, open it, add your user under *Users*.
   (Reviewer automatically includes the Employee rights.)
   - These groups install without a Settings-page toggle by design; assigning via
     the Groups list is the reliable path. Payroll staff who should review/approve
     get **TDS: Payroll Reviewer**; ordinary employees get **TDS: Employee**.

## Step 4 — Confirm the seeded rates
**Payroll → India TDS → Configuration → TDS Tax Configuration**. You should see
two records for **FY 2026-27** (New and Old) with the slabs from the README.

## Step 5 — UAT scenarios (we do this together)
Use **TEST Payroll Dummy** only. For each case: create a declaration
(**Payroll → India TDS → Tax Declarations → New**), fill the inputs, save, and
read the computed fields on the **Tax & Monthly TDS** tab. **Do not compute or
post a payslip until the read-only checks pass.**

| # | Scenario | Key inputs | Expect |
|---|----------|-----------|--------|
| 1 | New regime, mid salary | regime=New, projected remaining 15,00,000, months=10 | taxable_new 14,25,000; tax_new 97,500; monthly 9,750; recommends New |
| 2 | Old regime + 80C | regime=Old, projected 10,00,000, 80C 2,00,000 | 80C capped to 1,50,000; taxable_old 8,00,000 |
| 3 | No declarations | regime=New, projected 6,00,000 | taxable_new 5,25,000; tax_new 0; monthly 0 |
| 4 | Previous employer | New, projected 15,00,000, prev income 3,00,000, prev TDS 50,000 | tax rises; remaining tax reduced by 50,000 before spreading |
| 5 | High salary / surcharge | New, projected 60,00,000 | total tax 15,78,720 (10% surcharge band) |
| 6 | PAN missing | tick PAN missing | chatter notes it on submit; **no auto extra TDS** (flagged) |
| 7 | Write-back | approve case 1, set Contract Version to the dummy's version, click **Apply Monthly TDS to Contract** | `l10n_in_tds` on that hr.version becomes 9,750; chatter logs it |
| 8 | Payslip stays draft | (optional) recompute a **draft** payslip for the dummy | TDS line uses 9,750; **leave it Draft**; no posting; no journal entry |

### Hard stops during UAT (I will pause and ask first)
- touching any **real** employee,
- **validating/posting** a payslip,
- creating any **accounting** entry,
- changing **company-wide** payroll settings,
- modifying any **standard** localization rule.

After step 7, I can verify the written `l10n_in_tds` value on the dummy's
`hr.version` with read tools, and (if you want) set it via the narrow MCP write
tool instead of the module button — both are safe and DEV/company-2 scoped.
