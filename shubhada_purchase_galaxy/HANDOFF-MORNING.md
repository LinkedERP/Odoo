# ☀️ Morning handoff — Shubhada purchase screen

*Written overnight 21 Aug. Read this first; it takes two minutes.*

---

## ▶▶ WHERE THINGS STAND

**The amendment is built and it works.** That was the one thing Mahesh said with certainty
Odoo could not do, and it now does it — verified against real receipts, not a mock-up.

Module `shubhada_purchase_galaxy` is at **19.0.1.0.8**, live on **StagingDM**. Eight versions
overnight, every one of them a real fix found by testing rather than a guess.

---

## 1. THE AMENDMENT — what it actually does

Order **SHN27PO04190**: 4,000 kg of Hindalco copper at ₹862, received in two parts —
**1,500 kg on 5 Aug**, **1,200 kg on 14 Aug**, 1,300 kg still pending.

Revise the rate to **₹892 with effect from 10 August** and:

| Receipt | Date | Reached? |
|---|---|---|
| NSK12/IN/00175 | 5 Aug | **No** — before the effective date, stays at ₹862 |
| NSK12/IN/00176 | 14 Aug | **Yes** — revalued to ₹892 |

**Difference: ₹36,000**, on that receipt alone. Verified end to end over RPC.

Applying it also reprices the open 1,300 kg, sends the order **back through the approval
chain as amendment 1**, and writes the whole thing to the order's chatter.

**Where it lives:** open a posted order → **Amend Rate** (visible to HOD and Plant Head only),
or Purchase (Shubhada) → **Amendments**.

### ⚠️ The one honest limit
It does **not** post the correcting journal entry. This database has
`property_valuation = real_time` but **no stock valuation account** on the copper category,
so posting would create a half-formed entry on an instance shared with other customer demos.
The difference is computed and permanently recorded. Wiring the entry is a
chart-of-accounts configuration step, not a code change. **Say this to Mahesh — he will
respect it more than a claim that everything is finished.**

---

## 2. VIDEOS

Rendered with the engine's **free Windows rehearsal voice** — it sounds robotic, and that is
deliberate: the rate is calibrated to the real narrator, so pacing and sync survive the swap.
Add `ELEVENLABS_API_KEY` and re-render for the final voice; nothing else changes.

```
setx ELEVENLABS_API_KEY "your-key"
```
then
```
node src/engine/run.js specs/galaxy-po-screen.json --provider elevenlabs
node src/engine/run.js specs/galaxy-amendment.json --provider elevenlabs
```

Both specs are in `linkederp-video-engine/specs/`. Output lands in `output/`.

---

## 3. THE INSTANCE — four orders, each doing a job

| Record | Purpose |
|---|---|
| **P00246** (draft, no number) | The live order for video 1. Posting it reads **SHN27PO04204** — right after Mahesh's own 04203. |
| **SHN27PO04188** | July order at older rates, so **Last Rate** shows 13.50 → 14.00 instead of 0.00 |
| **SHN27CP00312** | A capital order **Mahesh cannot see** — proves the series segregation bites |
| **SHN27PO04190** | The copper contract with two GRNs, for the amendment |

**Cast:** Mahesh raises bought-out · Vilas raises capital · **Sachin** is HOD · **Devang** posts.

**To re-run the amendment demonstration:**
```
python shubhada_purchase_galaxy/RESET-AMENDMENT.py
```
Runs as Devang, because only an HOD may delete an amendment — running it as Mahesh fails
with an access error, which is the security working correctly.

---

## 4. WHAT I FIXED THAT WOULD HAVE EMBARRASSED YOU ON CAMERA

1. **The order list showed other customers' purchase orders** — Precitech, Hindalco,
   Accurate Engineering — because series-less orders were not excluded. On a shared demo
   instance, inside Shubhada's own screen. Fixed with a domain on the action.
2. **Nobody was in any of the six new groups**, so **Approve and Post were invisible to
   every user**. The video would have dead-ended at Submit.
3. **The HOD group granted no purchase access** — an approver could not open the order they
   were meant to approve.
4. **Receipts landed in a Mumbai warehouse (D506)** for a Nashik order, because the picking
   type defaulted. Rebuilt against NSK12.
5. **`Posted by` read "Akshay Jain"** on the seeded orders. Now Sachin approves, Devang posts.
6. **An applied amendment erased its own difference** — it recomputed to ₹0.00 at the exact
   moment it became evidence. The booked rate is now left alone.
7. **The amendment number read `AMD/NEW`** — the sequence had bound itself to company 1.
8. **The GRN grid was empty on a new amendment**, which is precisely when you need to look
   at it. It now fills as soon as you pick the item.

---

## 5. ODOO 19 GOTCHAS BANKED

Four builds failed before the module installed. All now written up in memory —
`reference_odoo19_api_changes` and `reference_odoo_sh_build_visibility`. The two that cost
the most:

- **`res.groups.category_id` is gone.** Odoo 19 moved grouping to a new `res.groups.privilege`
  model via `privilege_id`.
- **After a push, Odoo.sh keeps serving the OLD build** with no 503 — the old code just
  answers normally. A fix was pushed, installed, and reproduced the identical error. Every
  script now polls `installed_version` and refuses to install until the expected version is
  actually live.

---

## 6. NEXT

- Re-render both videos with the real voice once the key is in
- **Videos 2 and 3** (permissions; the whole line) — specs not written yet
- The **test-pack video**. His objection was never speed, it was *"60% of the time is
  testing."* Four videos of fast building, all untested, argues his side. Add one showing
  the tests running and it argues yours.
