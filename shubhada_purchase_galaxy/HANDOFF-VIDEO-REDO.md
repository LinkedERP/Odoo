# 🎬 HANDOFF — redo the four Shubhada purchase videos

*Written 2026-08-21 by the previous session, which produced four videos Akshay rejected.
Read this fully before touching anything. The build is finished and correct; **only the
videos are the problem**, and the reasons are known and written down below.*

---

## ▶▶ START HERE — the verdict

Akshay's words: *"the videos are not at all good quality, there are a lot of pauses, the
navigation is not good, you are not using ElevenLabs voice also, I need an Indian lady
with good English accent who can pronounce Shubada properly."*

All four criticisms are correct. **Three of them are my design decisions, not bad luck.**
Do not repeat them.

---

## 1. WHY THE VIDEOS ARE BAD — read this before re-recording

### 1.1 The pauses and the aimless pointer are MY doing

The engine refuses any take where the recording runs **more than 0.7s shorter than the
narration plan** (`src/engine/run.js`, the `A/V DESYNC` guard). Odoo freezes for ~1.2s
during server round-trips, and a frozen screen emits no frames, so takes kept failing.

My fix was to chop every hold into `hoverIf` + `wait` fragments, and — when hovering form
elements stopped working because Odoo unmounts them during a reload — to point those
hovers at **`.o_main_navbar`**. So the finished videos show the cursor **flicking to the
top navigation bar over and over for no reason**, with dead air between.

That is exactly the "lots of pauses, navigation is not good" Akshay is describing.

**Do not use hover-pulses. Use motion that means something:**
- **Slow scrolling** through a form while the narration talks — natural, continuous
  repaint, and it looks like a person reading.
- **Typing** — every keystroke repaints.
- Move the pointer **to the thing being talked about, once**, and leave it there while
  something else on screen moves.
- Where a genuine wait is unavoidable (a server round-trip), **cover it with narration
  that acknowledges it** rather than silence.

### 1.2 The narration is robotic because no ElevenLabs key was ever set

Every take was rendered with `--provider windows` — the free Windows SAPI rehearsal
voice. `ELEVENLABS_API_KEY` is **not set** on this machine. I checked; it is absent from
both the environment and the HKCU registry.

```
setx ELEVENLABS_API_KEY "<key>"      # then open a NEW terminal
node src/engine/run.js specs/<spec>.json --provider elevenlabs
```

**Akshay must supply the key. Ask for it first — nothing else matters until he does.**

### 1.3 Video 1 has no navigation because I removed it

The original cut walked Configuration → Purchase Series → back. Those menu transitions
drifted the take 1.2s out of sync **every single attempt**, so I deleted them. What's left
lands on a list and opens a record — thin, and it lost the six-series story.

Put the navigation back, and solve the sync properly (see 1.1).

---

## 2. THE VOICE — what he asked for

- **Indian woman, good English, must pronounce "Shubhada" correctly.**
- The specs already carry `voice_id: 1qEiC6qsybMkmnNdVMbK` — **Monika Sogam, "Calm and
  Natural"**, which is the Indian female voice Akshay himself picked for the Gate Entry
  video on 2026-08-20. Start there; he has already approved that voice once.
- **Test the pronunciation of "Shubhada" before rendering all four.** Render one line and
  listen. If it comes out wrong, spell it phonetically in the narration text —
  `Shubhaadaa` / `Shubh-aa-daa` — the spec text is never shown on screen, so spelling it
  for the synthesiser costs nothing.
- Also worth checking: **"Hindalco", "Nashik", "lakh", "GRN"** (say "G-R-N"), and the
  document number `SHN27PO04204`, which should be read as letters and digits, not as a
  word.

---

## 3. WHAT IS ALREADY BUILT AND CORRECT — do not rebuild this

### The module
`shubhada_purchase_galaxy` **19.0.1.1.1**, live on branch **StagingDM**, repo
`C:\Users\AkshayJain\odoo-sh-staging` (`LinkedERP/Odoo.git`). Fifteen commits, all pushed.

It answers Mahesh Joshi's objections from the 20 Aug call:
six purchase series each with its own running number and its own buyers · division on the
order · Galaxy numbering `SHN27PO04204` **issued on approval, not on save** · three-level
maker-checker with the raiser blocked from approving · amendments with per-GRN retroactive
repricing · per-line delivery schedules · last purchased rate · PR reference.

**Do not push code before recording.** See §5.1.

### The instance — `linked-staging2.odoo.com`, DB `linkederp-stagingdm-36147382`, company 4

| Record | Purpose |
|---|---|
| **P00246** (draft, no number) | The live order. Posting it reads **SHN27PO04204** — the next number after Mahesh's own 04203. |
| **SHN27PO04188** | July order at older rates, so **Last Rate** shows 13.50 → 14.00 |
| **SHN27CP00312** | A capital order the bought-out buyer **cannot see** — proves series segregation |
| **SHN27PO04190** | Copper, 4,000 kg, **three receipts at 845 / 862 / 875**, 500 kg pending — the amendment scenario |

**Cast** (password `Shubhada@2026` for all):

| Login | Role |
|---|---|
| `mahesh@shubhada.demo` | buyer, bought-out series only |
| `sachin@shubhada.demo` | HOD, first approval |
| `devang@shubhada.demo` | Plant Head, posts |
| `stores.nsk@shubhada.demo` | Vilas Pawar, capital buyer |

### The amendment demonstration
Revise **SHN27PO04190** to **₹892 effective 10 August**:

| Receipt | Date | Booked at | Result |
|---|---|---|---|
| NSK12/IN/00175 | 5 Aug | 845 | **untouched** |
| NSK12/IN/00176 | 14 Aug | 862 | repriced → **+₹36,000** |
| NSK12/IN/00177 | 20 Aug | 875 | repriced → **+₹13,600** |

**2 receipts affected, ₹49,600.** Verified end to end against real stock values.

---

## 4. HELPER SCRIPTS THAT ALREADY EXIST

In `C:\Users\AkshayJain\odoo-sh-staging\shubhada_purchase_galaxy\`:
- **`RESET-AMENDMENT.py`** — puts SHN27PO04190 back to three receipts at 845/862/875 with
  no amendment. Runs as **devang**, because only an HOD may delete an amendment.
- `SEED-GALAXY-PO.py` — waits for an Odoo.sh build to publish, then installs/upgrades.
- `HANDOFF-MORNING.md` — the build handoff.

In the scratchpad (`…\75a73316-…\scratchpad\`) — **copy these into the repo, they are worth keeping**:
- **`set_state.py draft|submitted|hod_approved`** — rewinds P00246 for a re-shoot. Writes
  with `tracking_disable` so the rewind does not appear in the chatter, and stamps the HOD
  time **in UTC** (Odoo renders in the user's timezone; a local timestamp comes back +5:30
  and the approval appears to happen after the posting).
- **`clear_chatter.py [res_id]`** — wipes a record's message history.
- `odoolib.py` — RPC helper, waits out 503s.

In `C:\Users\AkshayJain\linkederp-video-engine\`:
- `capture-login-galaxy2.cmd` — captures all four logins in one run.
- `specs/galaxy-*.json` — the seven specs. **Rewrite the beats; keep the narration text
  and the record numbers, which are correct and neutral.**
- `join-galaxy.sh` — joins the multi-take videos. Uses a relative concat list on purpose:
  ffmpeg is a Windows binary and mangles Git Bash `/c/...` paths.

---

## 5. TRAPS THAT COST HOURS — do not rediscover these

### 5.1 Every Odoo.sh rebuild kills the saved logins
Push code, and every `sessions/shubhada-*.json` becomes dead. **Freeze the code, then
capture logins, then record.** Verify before a long render:
```
node test-sessions.js        # prints OK / DEAD per session
```

### 5.2 A take that FAILS the sync check has still performed its clicks
The engine runs every beat, then checks sync. So a "failed" approval take really did
approve the order. **Rewind state before every retry** or the next attempt finds the wrong
row.

### 5.3 Odoo's tooltip eats row clicks
Playwright hovers before clicking, which pops Odoo's tooltip over the vendor cell, and the
tooltip then intercepts the click — it fails with *"`<span>S.S TRADERS</span>` … intercepts
pointer events"*. **Click the date cell of the row instead:**
`tbody tr.o_data_row:has-text("Draft") td[name="date_order"]`

### 5.4 The engine's `type` action reads `value`, not `text`
A wrong key types the literal string `undefined` and Odoo answers *"Missing required
fields"*. Add `"clear": true` to wipe a field before typing.

### 5.5 Readonly fields are not sent back on save
An onchange set a receipt's rate, the screen showed ₹36,000, and the save silently dropped
it because the column was `readonly` — every difference persisted as 0.00. Fixed by making
it `related` + `store=True`. Same family: **o2m rows invented by an onchange lose required
fields on save** — create the parent server-side and load children there.

### 5.6 Repricing a purchase line cascades onto its receipts
Odoo's own purchase code pushes the new price onto every stock move the line produced,
including ones deliberately left alone. The amendment snapshots and restores them. **When
seeding rates, write the LINE rate first, then the per-receipt rates** — the other order
wipes them.

### 5.7 Odoo 19 API changes
`res.groups.category_id` → **`res.groups.privilege`** via `privilege_id` · search-view
`<group>` rejects `string=` and `expand=` · `taxes_id` → `tax_ids` · `product_uom` →
`product_uom_id` · `stock.valuation.layer` is gone, value sits on `stock.move.value` ·
`res.users.groups_id` → `group_ids`. Full list in memory: `reference_odoo19_api_changes`.

---

## 6. THE FOUR VIDEOS TO REBUILD

Neutral narration throughout — **no "you said", no names, no "we built this for you"**.
Akshay asked for this explicitly. Around two minutes each, ideally shorter.

**① The purchase order screen** — as `mahesh`.
Six series with their own counters and buyers → open an order → **no number yet** → series,
location, validity, period → **last rate beside the new rate** → the PR it answers →
submit → **no approve button on the raiser's screen**. *Put the series navigation back.*

**② The rate amendment** — as `devang`.
Three receipts at three rates → revise to 892 from 10 Aug → one untouched, two repriced by
**different amounts** → **₹49,600** → applied, with who and when.
Run `RESET-AMENDMENT.py` before each take.

**③ Access restriction** — two takes, `mahesh` then `stores.nsk`, joined.
Bought-out buyer searches for the capital order → nothing. Capital buyer opens the same
menu → that order is all they have. *"One database, two people, two sets of data."*

**④ Three levels of approval** — three takes, `mahesh` → `sachin` → `devang`, joined.
Submit (no number, no approve button) → HOD approves → plant head posts and
**`SHN27PO04204`** appears → close on the Audit tab: three names, three timestamps.
Rewind with `set_state.py` between takes; clear the chatter before the first one.

---

## 7. HOW AKSHAY WANTS TO BE WORKED WITH

- **Explain like he's five.** Non-technical. Plain words, everyday comparisons.
- **Never guess a number — read it off the instance first.** He notices, and it costs
  confidence.
- **Short answers, lead with the answer.**
- **When he says something is wrong, believe him.** He was right about the videos, right
  that the amendment grid looked identical on both lines (which turned out to be a real
  bug), and right that the original demo lacked a spine.
- Own corrections plainly and move on. No over-apologising.

---

## 8. FIRST THREE THINGS TO DO IN THE NEW SESSION

1. **Ask for the ElevenLabs API key.** Nothing ships without it.
2. **Render one line with the Monika Sogam voice and check "Shubhada".** Get his ear on it
   before building four videos on top of a voice he might reject.
3. **Rebuild the beats around continuous motion** — scrolling and typing, not hover-pulses
   — and prove the approach on ONE take before committing to all seven.
