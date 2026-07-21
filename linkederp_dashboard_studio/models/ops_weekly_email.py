"""Tuesday Ops Weekly emails — the in-Odoo agent.

Every Tuesday morning (ir.cron, ships INACTIVE) this builds and emails:
  - one insight email per squad (Operations Team) to its OD(s) from the
    "Manages Team" mapping, and
  - one MD brief (Chief-of-Staff style) to the addresses in the
    ``linkederp_dashboard.ops_email_md_to`` parameter.

All numbers come from the Ops Weekly review dashboard's OWN widget payload
(``_ops_dashboard_widgets`` per squad + org) so the emails can never disagree
with the dashboard. Three extra read_groups add the analysis layer: hours per
project (reviewed week + prior → stalled projects), and hours per
user × project × invoice type (where each person's time went, non-billable
sinks, squad billable-concentration).

Safety: while ``linkederp_dashboard.ops_email_test_to`` is set (defaulted to
Akshay on first load) every email goes ONLY there with a "[TEST] " subject
prefix. ``linkederp_dashboard.ops_email_last_week`` guards the real cron path
against double sends. The pure helpers are ported verbatim from the reviewed
preview generator (docs/superpowers/weekly_ops_email.py, W29 drafts approved
by Akshay 2026-07-21).
"""
import logging
from datetime import datetime, timedelta
from html import escape

from odoo import api, fields, models

from .ops_dashboard import OPS_DASHBOARD_NAME

_logger = logging.getLogger(__name__)

OPS_EMAIL_TEST_PARAM = "linkederp_dashboard.ops_email_test_to"
OPS_EMAIL_MD_PARAM = "linkederp_dashboard.ops_email_md_to"
OPS_EMAIL_LAST_PARAM = "linkederp_dashboard.ops_email_last_week"
OPS_EMAIL_TEST_DEFAULT = "akshay@linkederp.com"

GREEN, AMBER, RED, BLUE, GREY = "#2e7d2e", "#c98a1b", "#b03030", "#1d4ed8", "#64748b"
BILL_TARGET = 75.0


# ---------------------------------------------------------------------------
# Pure helpers (ported from the approved preview generator — keep in sync)
# ---------------------------------------------------------------------------
def _widget(payload, wid):
    for w in payload["widgets"]:
        if w.get("id") == wid:
            return w
    return {}


def _fnum(text):
    try:
        return float(str(text).replace("%", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _money_parse(text):
    """'Rp212,602,041' -> (212602041.0, 'Rp'); '—' -> (0.0, '—')."""
    t = str(text or "").strip()
    digits = "".join(c for c in t if c.isdigit() or c in ".-")
    try:
        val = float(digits) if digits not in ("", "-", ".") else 0.0
    except ValueError:
        val = 0.0
    sym = ""
    for c in t:
        if c.isdigit() or c == "-":
            break
        sym += c
    return val, sym.strip()


def _money_fmt(val, sym):
    return "%s%s" % (sym, "{:,.0f}".format(round(val)))


def _parse_end_date(text):
    try:
        return datetime.strptime(str(text).strip(), "%d %b %Y").date()
    except ValueError:
        return None


def _detail_rows(point):
    detail = (point or {}).get("detail") or {}
    rows = [{"name": r["name"], "a": _fnum(r["cells"][0]), "b": _fnum(r["cells"][1]),
             "pct": _fnum(r["cells"][2])} for r in detail.get("rows", [])]
    t = detail.get("total") or {}
    cells = t.get("cells") or ["0", "0", "0"]
    total = {"a": _fnum(cells[0]), "b": _fnum(cells[1]), "pct": _fnum(cells[2])}
    return rows, total, detail.get("more") or ""


def _person_series(points):
    """{name: [(week_label, expected, actual, pct)]} oldest -> newest."""
    out = {}
    for pt in points or []:
        rows, _t, _m = _detail_rows(pt)
        for r in rows:
            out.setdefault(r["name"], []).append(
                (pt.get("label", ""), r["a"], r["b"], r["pct"]))
    return out


def _last_two(points):
    pts = points or []
    return (pts[-1] if pts else {}), (pts[-2] if len(pts) > 1 else {})


def _wow(cur, prev):
    if not cur or not prev:
        return ""
    delta = round(_fnum(cur.get("value")) - _fnum(prev.get("value")), 1)
    if abs(delta) < 0.05:
        return " (same as last week)"
    return " (%s%s pts vs last week)" % ("▲+" if delta > 0 else "▼−", abs(delta))


def _tone(pct, good=100.0, warn=90.0):
    return GREEN if pct >= good else AMBER if pct >= warn else RED


def _h(x):
    v = round(x, 1)
    return "%d" % v if v == int(v) else "%.1f" % v


def _dedupe_names(names):
    """['Ferry Nauli (ID)', 'Ferry Nauli (IN)'] -> 'Ferry Nauli'."""
    seen = []
    for name in names:
        base = (name or "").split(" (")[0].strip()
        if base and base not in seen:
            seen.append(base)
    return " & ".join(seen)


def _first_name(full):
    return (full or "").split(" (")[0].split()[0] if full else "there"


def _poss(name):
    return name + ("'" if name.endswith("s") else "'s")


def _trend_story(series):
    """[(label, value)] -> dict(direction, start, end, ...) or None."""
    pts = [(l, v) for l, v in series if v is not None]
    if len(pts) < 2:
        return None
    vals = [v for _l, v in pts]
    falls = rises = 0
    for a, b in zip(vals[-2::-1], vals[::-1]):  # consecutive falls at the end
        if b < a - 0.05:
            falls += 1
        else:
            break
    for a, b in zip(vals[-2::-1], vals[::-1]):  # consecutive rises at the end
        if b > a + 0.05:
            rises += 1
        else:
            break
    net = vals[-1] - vals[0]
    if (falls >= 2 and net < -1) or net <= -5:
        direction = "falling"
    elif (rises >= 2 and net > 1) or net >= 5:
        direction = "rising"
    else:
        direction = "stable"
    return {"direction": direction, "start": vals[0], "end": vals[-1],
            "start_label": pts[0][0], "end_label": pts[-1][0],
            "falls": falls, "net": net}


def _squad_payload_data(payload):
    """Everything one email needs, extracted from one widgets payload."""
    pass_card = _widget(payload, "ops_pass_rate")
    cov_card = _widget(payload, "ops_coverage")
    pass_w = _widget(payload, "ops_pass_trend")
    cov_w = _widget(payload, "ops_coverage_trend")
    pass_pt, pass_prev = _last_two(pass_w.get("points"))
    cov_pt, cov_prev = _last_two(cov_w.get("points"))
    bill_w = _widget(payload, "ops_billability_trend")
    bill_pt, bill_prev = _last_two(bill_w.get("points"))
    plan_w = _widget(payload, "ops_planning_trend")
    plan_pts = plan_w.get("points") or []
    plan_next = plan_pts[0] if plan_pts else {}

    cov_rows, cov_total, cov_more = _detail_rows(cov_pt)
    pass_rows, _pt, _pm = _detail_rows(pass_pt)
    bill_rows, bill_total, _bm = _detail_rows(bill_pt)
    plan_rows, _plt, _plm = _detail_rows(plan_next)

    people = {}
    for r in cov_rows:
        people[r["name"]] = {"name": r["name"], "exp": r["a"], "act": r["b"], "cov": r["pct"],
                             "lines": 0, "ontime": 0, "passp": None,
                             "expb": 0.0, "bill": 0.0, "billp": None, "plan": None}
    for r in pass_rows:
        p = people.setdefault(r["name"], {"name": r["name"], "exp": 0, "act": 0, "cov": 0,
                                          "expb": 0, "bill": 0, "billp": None, "plan": None})
        p.update(lines=int(r["a"]), ontime=int(r["b"]), passp=r["pct"])
    for r in bill_rows:
        if r["name"] in people:
            people[r["name"]].update(expb=r["a"], bill=r["b"], billp=r["pct"])
    for r in plan_rows:
        if r["name"] in people:
            people[r["name"]]["plan"] = r["b"]

    projects = []
    for r in _widget(payload, "ops_projects").get("rows") or []:
        row = dict(r)
        dom = r.get("domain") or []
        row["pid"] = dom[0][2] if dom and len(dom[0]) == 3 else None
        modals = r.get("cell_modals") or {}
        row["so_series"] = [(p.get("label", ""), p.get("value"))
                            for p in (modals.get("prof_so") or {}).get("points", [])]
        row["inv_series"] = [(p.get("label", ""), p.get("value"))
                             for p in (modals.get("prof_inv") or {}).get("points", [])]
        row["so_val"], row["sym"] = _money_parse(r.get("so_amount"))
        row["cost_val"], _s = _money_parse(r.get("cost"))
        row["inv_val"], _s = _money_parse(r.get("invoiced"))
        row["planned_v"] = _fnum(r.get("planned_hrs"))
        row["actual_v"] = _fnum(r.get("actual_hrs"))
        row["end_date"] = _parse_end_date(r.get("end"))
        projects.append(row)

    return {
        "pass_rate": _fnum(pass_card.get("value")), "pass_measure": pass_card.get("measure", ""),
        "pass_wow": _wow(pass_pt, pass_prev),
        "coverage": _fnum(cov_card.get("value")), "cov_measure": cov_card.get("measure", ""),
        "cov_wow": _wow(cov_pt, cov_prev), "cov_total": cov_total, "cov_more": cov_more,
        "bill": _fnum(bill_pt.get("value")), "bill_avg": _fnum(bill_w.get("value")),
        "bill_wow": _wow(bill_pt, bill_prev), "bill_total": bill_total,
        "plan_next": _fnum(plan_next.get("value")), "plan_avg": _fnum(plan_w.get("value")),
        "plan_next_label": plan_next.get("label", ""),
        "people": sorted(people.values(), key=lambda p: (-p.get("exp", 0), p["name"].lower())),
        "bill_series": _person_series(bill_w.get("points")),
        "cov_series": _person_series(cov_w.get("points")),
        "pass_series": _person_series(pass_w.get("points")),
        "projects": projects,
        "sla_610": int(_fnum(_widget(payload, "ops_sla_610").get("value"))),
        "sla_g10": int(_fnum(_widget(payload, "ops_sla_g10").get("value"))),
        "sla_hold": int(_fnum(_widget(payload, "ops_sla_hold").get("value"))),
        "sla_rows": _widget(payload, "ops_sla_customers").get("rows") or [],
    }


# ------------------------------------------------------- insight stories ----
def _split_text(name, person_split, limit=3):
    projects = (person_split or {}).get(name) or {}
    items = sorted(projects.items(), key=lambda kv: -kv[1][0])[:limit]
    if not items:
        return ""
    parts = []
    for proj, (tot, bill) in items:
        if bill < 0.5:
            tag = "non-billable"
        elif bill >= tot - 0.5:
            tag = "billable"
        else:
            tag = "%s h billable" % _h(bill)
        parts.append("%s (%s h, %s)" % (proj, _h(tot), tag))
    return " Last week the hours went to: %s." % "; ".join(parts)


def _squad_billable_by_project(people, person_split):
    agg = {}
    for p in people:
        for proj, (_tot, bill) in ((person_split or {}).get(p["name"]) or {}).items():
            if bill > 0.5:
                agg[proj] = agg.get(proj, 0.0) + bill
    return agg


def _squad_concentration(people, person_split):
    agg = _squad_billable_by_project(people, person_split)
    total = sum(agg.values())
    if total < 20:
        return None
    proj, hrs = max(agg.items(), key=lambda kv: kv[1])
    share = hrs / total * 100
    if share >= 60:
        return ("amber", "Billable concentration",
                "%s%% of the squad's billable hours (%s of %s h) sit on one project — %s. "
                "When it winds down, billability falls with it; worth lining up what comes "
                "next." % (_h(share), _h(hrs), _h(total), proj))
    return None


def _people_stories(d, person_split=None):
    stories = []
    flagged = set()
    for name, series in sorted(d["bill_series"].items()):
        pts = [(l, pct) for l, a, _b, pct in series if a > 0]
        if len(pts) >= 3:
            (l1, v1), (l2, v2), (l3, v3) = pts[-3:]
            if v1 > v2 > v3 and v1 - v3 >= 10:
                stories.append((0, "red", name,
                                "%s billability keeps sliding: %s%% → %s%% → %s%% over the "
                                "last three weeks (%s–%s).%s"
                                % (_poss(_first_name(name)), _h(v1), _h(v2), _h(v3), l1, l3,
                                   _split_text(name, person_split))))
                flagged.add(name)
                continue
            if v3 > v2 > v1 and v3 - v1 >= 15:
                stories.append((3, "green", name,
                                "%s is trending the right way on billability: %s%% → %s%% → "
                                "%s%% (%s–%s)." % (_first_name(name), _h(v1), _h(v2), _h(v3),
                                                   l1, l3)))
                flagged.add(name)
        if name not in flagged and len(pts) >= 2:
            recent = pts[-2:]
            if all(v < 40 for _l, v in recent):
                stories.append((1, "red", name,
                                "%s has spent two straight weeks mostly on non-billable work "
                                "(%s%% then %s%% billability).%s"
                                % (_first_name(name), _h(recent[0][1]), _h(recent[1][1]),
                                   _split_text(name, person_split))))
                flagged.add(name)
    for name, series in sorted(d["cov_series"].items()):
        pts = [(l, pct) for l, a, _b, pct in series if a > 0]
        low = [(l, v) for l, v in pts[-3:] if v < 90]
        if len(low) >= 2:
            stories.append((1, "amber", name,
                            "%s has under-logged hours in %d of the last 3 weeks (%s). The "
                            "hours may be worked but they are not in the system."
                            % (_first_name(name), len(low),
                               ", ".join("%s at %s%%" % (l, _h(v)) for l, v in low))))
    for name, series in sorted(d["pass_series"].items()):
        pts = [(l, pct) for l, a, _b, pct in series if a > 0]
        late = [l for l, v in pts[-4:] if v < 100]
        if len(late) >= 2:
            stories.append((2, "amber", name,
                            "%s has entered timesheets late in %d of the last 4 weeks (%s) — "
                            "a habit forming, not a one-off." % (_first_name(name), len(late),
                                                                 ", ".join(late))))
    stories.sort(key=lambda s: s[0])
    return [(t, n, txt) for _rank, t, n, txt in stories[:6]]


def _project_stories(d, hours_by_pid, today):
    stories = []
    for r in d["projects"]:
        name = r.get("label", "?")
        story = _trend_story(r["inv_series"]) or _trend_story(r["so_series"])
        bad = r.get("tones", {}).get("prof_so") == "bad" or \
            r.get("tones", {}).get("prof_inv") == "bad"
        # A falling margin that is still comfortably healthy (>=60%) is not
        # news for an OD — only flag falls that land somewhere worrying.
        if story and story["direction"] == "falling" and abs(story["net"]) >= 2 \
                and story["end"] < 60:
            burn = ""
            pid = r.get("pid")
            if pid is not None and pid in hours_by_pid:
                h_last, h_prev = hours_by_pid[pid]
                if h_last >= 8 and h_last > 1.5 * max(h_prev, 0.1):
                    burn = (" It is also burning faster: %s h logged last week vs %s the "
                            "week before." % (_h(h_last), _h(h_prev)))
            stories.append((0, "red", name,
                            "Profitability trend is DOWN: invoiced margin went %s%% → %s%% "
                            "over the last %s weeks (%s to %s).%s"
                            % (_h(story["start"]), _h(story["end"]),
                               len([v for _l, v in r["inv_series"] or
                                    r["so_series"] if v is not None]),
                               story["start_label"], story["end_label"], burn)))
        elif bad and story and story["direction"] == "stable":
            stories.append((1, "red", name,
                            "Margin has been flat around %s%% for weeks — stable, but "
                            "stable at a loss." % _h(story["end"])))
        elif story and story["direction"] == "rising" and bad:
            stories.append((3, "amber", name,
                            "Still loss-making but recovering: margin improved %s%% → %s%% "
                            "over recent weeks." % (_h(story["start"]), _h(story["end"]))))
        if r.get("so_val", 0) > 0 and r.get("cost_val", 0) > r["so_val"]:
            stories.append((0, "red", name,
                            "Cost to date (%s) now exceeds the sale-order value (%s) by %s."
                            % (_money_fmt(r["cost_val"], r["sym"]),
                               _money_fmt(r["so_val"], r["sym"]),
                               _money_fmt(r["cost_val"] - r["so_val"], r["sym"]))))
        pid = r.get("pid")
        if pid is not None and pid in hours_by_pid:
            h_last, h_prev = hours_by_pid[pid]
            if h_last < 0.5:
                extra = " — second week running" if h_prev < 0.5 else ""
                stories.append((1, "amber", name,
                                "No work logged last week%s. If the project is waiting on "
                                "the customer, note it; if not, it is silently slipping."
                                % extra))
        if r.get("planned_v", 0) > 0 and r.get("actual_v", 0) > 1.1 * r["planned_v"]:
            stories.append((2, "amber", name,
                            "Hours overrun: %s h logged vs %s h planned (%s%%)."
                            % (_h(r["actual_v"]), _h(r["planned_v"]),
                               _h(r["actual_v"] / r["planned_v"] * 100))))
        if r.get("end_date") and r["end_date"] < today:
            stories.append((2, "amber", name,
                            "Past its expected end date (%s) but still active — either "
                            "re-plan the date or close it out."
                            % r["end_date"].strftime("%d %b %Y")))
    # One bullet per project: the most severe finding leads, the rest chain on.
    stories.sort(key=lambda s: s[0])
    merged, order = {}, []
    for _rank, t, n, txt in stories:
        if n in merged:
            merged[n][1] += " Also: " + txt[0].lower() + txt[1:]
        else:
            merged[n] = [t, txt]
            order.append(n)
    return [(merged[n][0], n, merged[n][1]) for n in order[:6]]


def _support_stories(d):
    stories = []
    if d["sla_g10"]:
        top = d["sla_rows"][0] if d["sla_rows"] else None
        txt = "%d ticket(s) have been open more than 10 working days" % d["sla_g10"]
        if top:
            txt += " — %s alone holds %d of them" % (top["label"], int(_fnum(top.get("dg10"))))
        stories.append(("red", "Ageing tickets", txt + "."))
    if d["sla_hold"] >= 10:
        stories.append(("amber", "On hold",
                        "%d tickets sit on hold. On-hold is where tickets go to be "
                        "forgotten — worth a monthly sweep." % d["sla_hold"]))
    return stories


# --------------------------------------------------------------- render ----
CARD = ("<td style='padding:12px 14px;background:#f8fafc;border:1px solid #e2e8f0;"
        "border-radius:8px;vertical-align:top;'>"
        "<div style='font-size:11px;color:%(grey)s;text-transform:uppercase;"
        "letter-spacing:.4px;'>%(title)s</div>"
        "<div style='font-size:24px;font-weight:700;color:%(color)s;padding:2px 0;'>%(big)s</div>"
        "<div style='font-size:11px;color:%(grey)s;'>%(sub)s</div></td>")

TD = "padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:12px;"
TH = ("padding:6px 8px;border-bottom:2px solid #cbd5e1;font-size:11px;color:#475569;"
      "text-align:left;text-transform:uppercase;letter-spacing:.3px;")
TONES = {"red": RED, "amber": AMBER, "green": GREEN}


def _card(title, big, sub, color):
    return CARD % {"title": escape(title), "big": escape(big), "sub": escape(sub),
                   "color": color, "grey": GREY}


def _story_list(stories):
    items = "".join(
        "<li style='margin:8px 0;font-size:13px;line-height:1.5;color:#1e293b;'>"
        "<b style='color:%s;'>%s</b> — %s</li>"
        % (TONES[t], escape(label), escape(text)) for t, label, text in stories)
    return "<ul style='margin:8px 0 4px;padding-left:18px;'>%s</ul>" % items


def _pct_cell(value, good=100.0, warn=90.0):
    if value is None:
        return "<td style='%s'>—</td>" % TD
    return ("<td style='%sfont-weight:700;color:%s;'>%s%%</td>"
            % (TD, _tone(value, good, warn), _h(value)))


def _people_table(people, more):
    head = "".join("<th style='%s'>%s</th>" % (TH, c) for c in
                   ["Person", "Expected h", "Logged h", "Coverage",
                    "Billable h", "Billability", "Lines on time", "Pass"])
    body = []
    for p in people:
        ontime = ("%d / %d" % (p["ontime"], p["lines"])) if p.get("lines") else "—"
        body.append(
            "<tr><td style='%s'>%s</td><td style='%s'>%s</td><td style='%s'>%s</td>"
            % (TD, escape(p["name"]), TD, _h(p.get("exp", 0)), TD, _h(p.get("act", 0)))
            + _pct_cell(p.get("cov") if p.get("exp") else None)
            + "<td style='%s'>%s</td>" % (TD, _h(p.get("bill", 0)))
            + _pct_cell(p.get("billp") if p.get("expb") else None, good=75.0, warn=60.0)
            + "<td style='%s'>%s</td>" % (TD, ontime)
            + _pct_cell(p.get("passp") if p.get("lines") else None) + "</tr>")
    extra = ("<div style='font-size:11px;color:%s;padding:4px 0;'>%s</div>"
             % (GREY, escape(more)) if more else "")
    return ("<table cellspacing='0' cellpadding='0' style='width:100%%;border-collapse:"
            "collapse;'><tr>%s</tr>%s</table>%s" % (head, "".join(body), extra))


def _projects_table(rows):
    if not rows:
        return "<div style='font-size:12px;color:%s;'>No active projects mapped.</div>" % GREY
    cols = [("label", "Project"), ("stage", "Stage"), ("end", "Expected end"),
            ("planned_hrs", "Planned h"), ("actual_hrs", "Actual h"),
            ("so_amount", "SO amount"), ("invoiced", "Invoiced"), ("cost", "Cost"),
            ("prof_so", "% Prof (SO)"), ("prof_inv", "% Prof (Inv)")]
    head = "".join("<th style='%s'>%s</th>" % (TH, label) for _k, label in cols)
    body = []
    for r in rows:
        cells = []
        for key, _label in cols:
            style = TD
            t = r.get("tones", {}).get(key)
            if t:
                style += "font-weight:700;color:%s;" % {"good": GREEN, "warn": AMBER,
                                                        "bad": RED}[t]
            cells.append("<td style='%s'>%s</td>" % (style, escape(str(r.get(key, "")))))
        body.append("<tr>%s</tr>" % "".join(cells))
    return ("<div style='overflow-x:auto;'><table cellspacing='0' cellpadding='0' "
            "style='width:100%%;border-collapse:collapse;'>"
            "<tr>%s</tr>%s</table></div>" % (head, "".join(body)))


def _sla_block(d):
    line = ("<b style='color:%s'>%d</b> open 6–10 days · <b style='color:%s'>%d</b> open "
            "&gt;10 days · <b style='color:%s'>%d</b> on hold"
            % (AMBER, d["sla_610"], RED, d["sla_g10"], AMBER, d["sla_hold"]))
    rows = "".join(
        "<tr><td style='%s'>%s</td><td style='%s'>%d</td><td style='%s'>%d</td></tr>"
        % (TD, escape(r["label"]), TD, int(_fnum(r.get("d610", 0))), TD,
           int(_fnum(r.get("dg10", 0)))) for r in d["sla_rows"][:8])
    table = ("<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;"
             "min-width:340px;'><tr><th style='%s'>Customer</th><th style='%s'>6–10 d</th>"
             "<th style='%s'>&gt;10 d</th></tr>%s</table>" % (TH, TH, TH, rows)
             if rows else "")
    return "<div style='font-size:13px;padding:4px 0 8px;'>%s</div>%s" % (line, table)


def _section(title, inner):
    return ("<h3 style='font-size:14px;color:#0f172a;margin:22px 0 6px;'>%s</h3>%s"
            % (escape(title), inner))


def _email_shell(title, subtitle, body):
    return ("<div style='font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:0 auto;"
            "background:#ffffff;'>"
            "<div style='background:%s;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;'>"
            "<div style='font-size:18px;font-weight:700;'>%s</div>"
            "<div style='font-size:12px;opacity:.85;'>%s</div></div>"
            "<div style='padding:16px 20px;border:1px solid #e2e8f0;border-top:0;"
            "border-radius:0 0 8px 8px;'>%s"
            "<div style='font-size:11px;color:%s;margin-top:24px;border-top:1px solid #e2e8f0;"
            "padding-top:8px;'>Generated automatically from the Ops Weekly review dashboard — "
            "numbers match the dashboard exactly. Reply if something looks off.</div>"
            "</div></div>" % (BLUE, escape(title), escape(subtitle), body, GREY))


def _kpi_row(cards):
    tds = "<td style='width:12px;'></td>".join(cards)
    return ("<table cellspacing='0' cellpadding='0' style='width:100%%;border-collapse:"
            "separate;'><tr>%s</tr></table>" % tds)


def _od_email(squad_label, od_name, week_label, d, ppl, proj):
    cards = [
        _card("Time entry pass rate", "%s%%" % _h(d["pass_rate"]),
              "%s%s" % (d["pass_measure"], d["pass_wow"]), _tone(d["pass_rate"])),
        _card("Time entry coverage", "%s%%" % _h(d["coverage"]),
              "%s%s" % (d["cov_measure"], d["cov_wow"]), _tone(d["coverage"])),
        _card("Billability", "%s%%" % _h(d["bill"]),
              "target 75%% · 8-wk avg %s%%%s" % (_h(d["bill_avg"]), d["bill_wow"]),
              _tone(d["bill"], good=75, warn=60)),
        _card("Planning next week", "%s%%" % _h(d["plan_next"]),
              "%s · 8-wk avg %s%%" % (d["plan_next_label"], _h(d["plan_avg"])),
              _tone(d["plan_next"], good=75, warn=60)),
    ]
    supp = _support_stories(d)
    hygiene = []
    late = [p for p in d["people"] if p.get("lines") and p["ontime"] < p["lines"]]
    if late:
        hygiene.append(("red", "Late entries",
                        ", ".join("%s (%d of %d on time)" % (p["name"], p["ontime"], p["lines"])
                                  for p in late[:5]) + "."))
    unplanned = [p for p in d["people"] if p.get("exp", 0) > 0 and (p.get("plan") or 0) <= 0]
    if unplanned and d["plan_next"] < 75:
        hygiene.append(("amber", "Next week's plan",
                        "%s%% planned for %s — %s not scheduled yet."
                        % (_h(d["plan_next"]), d["plan_next_label"],
                           ", ".join(p["name"] for p in unplanned[:5]))))
    insights = ppl + hygiene
    body = (
        "<p style='font-size:13px;color:#1e293b;'>Hi %s,<br>here is what last week's data "
        "(%s) is actually saying about <b>%s</b> — trends first, tables after.</p>" %
        (escape(_first_name(od_name)), escape(week_label), escape(squad_label))
        + _kpi_row(cards)
        + _section("Your people — what the trends say",
                   _story_list(insights) if insights else
                   "<div style='font-size:13px;color:%s;'>Nothing trending the wrong way — a "
                   "genuinely clean week for the team. 👏</div>" % GREY)
        + (_section("Your projects — direction, not just position", _story_list(proj))
           if proj else "")
        + (_section("Support", _story_list(supp)) if supp else "")
        + _section("The numbers behind it — person by person",
                   _people_table(d["people"], d["cov_more"]))
        + _section("Project financials", _projects_table(d["projects"]))
        + _section("Ticket ageing detail", _sla_block(d))
    )
    return _email_shell("Ops Weekly · %s" % squad_label,
                        "%s · for %s" % (week_label, od_name or "team lead"), body)


def _md_league(squads):
    head = "".join("<th style='%s'>%s</th>" % (TH, c) for c in
                   ["Squad (OD)", "People", "Pass", "Coverage", "Billability", "Next-wk plan"])
    body = []
    for s in sorted(squads, key=lambda s: -(s["d"]["coverage"] + s["d"]["bill"])):
        d = s["d"]
        body.append(
            "<tr><td style='%s'><b>%s</b> · %s</td><td style='%s'>%d</td>"
            % (TD, escape(s["label"]), escape(s["od"] or "—"), TD, len(d["people"]))
            + _pct_cell(d["pass_rate"]) + _pct_cell(d["coverage"])
            + _pct_cell(d["bill"], good=75, warn=60)
            + _pct_cell(d["plan_next"], good=75, warn=60) + "</tr>")
    return ("<table cellspacing='0' cellpadding='0' style='width:100%%;border-collapse:"
            "collapse;'><tr>%s</tr>%s</table>" % (head, "".join(body)))


def _shared_token(labels):
    stop = {"project", "template", "phase", "netsuite", "odoo", "support", "system"}
    counts = {}
    for label in labels:
        words = {w.strip(",.:-()").lower() for w in label.split() if len(w.strip(",.:-()")) >= 4}
        for w in words - stop:
            counts[w] = counts.get(w, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1], default=(None, 0))
    return (best[0].upper(), best[1]) if best[1] >= 2 else (None, 0)


def _md_headline(org, squads):
    if org["pass_rate"] >= 98 and org["coverage"] >= 98 and org["bill"] < BILL_TARGET - 5:
        return ("Discipline is no longer the problem — utilisation is. The team logged "
                "%s%% of expected hours and %s%% of lines on time, but only %s%% of "
                "billable capacity was actually billed (8-week average %s%% — this is "
                "structural, not a bad week)."
                % (_h(org["coverage"]), _h(org["pass_rate"]), _h(org["bill"]),
                   _h(org["bill_avg"])))
    if org["bill"] >= BILL_TARGET and org["pass_rate"] >= 98:
        return ("A strong week: discipline held (%s%% on time, %s%% coverage) and "
                "billability hit target at %s%%."
                % (_h(org["pass_rate"]), _h(org["coverage"]), _h(org["bill"])))
    return ("Mixed week: pass rate %s%%, coverage %s%%, billability %s%% against the "
            "75%% target." % (_h(org["pass_rate"]), _h(org["coverage"]), _h(org["bill"])))


def _md_working(org, squads, person_split=None):
    items = []
    if org["pass_rate"] >= 98:
        items.append(("green", "Discipline",
                      "%s — the time-entry habit is now fully embedded%s."
                      % (org["pass_measure"], org["pass_wow"])))
    best = max(squads, key=lambda s: s["d"]["bill"], default=None)
    if best and best["d"]["bill"] >= BILL_TARGET:
        agg = _squad_billable_by_project(best["d"]["people"], person_split)
        driver = ""
        if agg:
            proj, hrs = max(agg.items(), key=lambda kv: kv[1])
            driver = (" — driven mainly by %s (%s of the squad's %s billable h last week)"
                      % (proj, _h(hrs), _h(sum(agg.values()))))
        at_target = [s for s in squads if s["d"]["bill"] >= BILL_TARGET]
        label = ("The only squad at target billability" if len(at_target) == 1
                 else "At target billability")
        items.append(("green", best["label"],
                      "%s (%s%%)%s." % (label, _h(best["d"]["bill"]), driver)))
    gains = [(s, n, txt) for sq in squads for (t, n, txt) in sq.get("ppl_stories", [])
             for s in [sq] if t == "green"]
    if gains:
        items.append(("green", "Improving",
                      "; ".join("%s (%s)" % (n, s["label"]) for s, n, _t in gains[:3])
                      + " — billability visibly recovering."))
    if org["plan_next"] >= 80:
        items.append(("green", "Planning",
                      "Next week is %s%% planned already — the forward book is healthy."
                      % _h(org["plan_next"])))
    return items


def _md_attention(org, squads, today, sinks=None):
    items = []
    gap = max(0.0, org["bill_total"]["a"] - org["bill_total"]["b"])
    if org["bill"] < BILL_TARGET and gap > 0:
        contrib = sorted(squads, key=lambda s: -(s["d"]["bill_total"]["a"]
                                                 - s["d"]["bill_total"]["b"]))
        top = contrib[0] if contrib else None
        top_txt = ""
        if top:
            tgap = top["d"]["bill_total"]["a"] - top["d"]["bill_total"]["b"]
            top_txt = (" %s drives the biggest share (%s of the %s h)."
                       % (top["label"], _h(max(tgap, 0)), _h(gap)))
        people = [(p["name"], s["label"], p["expb"] - p["bill"])
                  for s in squads for p in s["d"]["people"]
                  if p.get("expb", 0) > 0 and (p["expb"] - p["bill"]) >= 8
                  and (p.get("billp") or 0) < 50]
        people.sort(key=lambda x: -x[2])
        names = (" The biggest individual gaps: "
                 + ", ".join("%s (%s h unbilled, %s)" % (n, _h(g), sq)
                             for n, sq, g in people[:3]) + ".") if people else ""
        sink_txt = ""
        top_sinks = sorted((sinks or {}).items(), key=lambda kv: -kv[1])[:3]
        top_sinks = [(p, v) for p, v in top_sinks if v >= 8]
        if top_sinks:
            sink_txt = (" Where it leaks: the biggest non-billable time sinks were %s."
                        % "; ".join("%s (%s h)" % (p, _h(v)) for p, v in top_sinks))
        items.append(("red", "Unbilled capacity",
                      "~%s hours of expected billable capacity went unbilled last week "
                      "(%s of %s h).%s%s%s" % (_h(gap), _h(org["bill_total"]["b"]),
                                               _h(org["bill_total"]["a"]), top_txt, names,
                                               sink_txt)))
    red_rows = [(s["label"], r) for s in squads for r in s["d"]["projects"]
                if r.get("tones", {}).get("prof_so") == "bad"
                or r.get("tones", {}).get("prof_inv") == "bad"]
    seen, uniq = set(), []
    for _sq, r in red_rows:
        if r["label"] not in seen:
            seen.add(r["label"])
            uniq.append(r)
    if uniq:
        losses = []
        for r in uniq:
            if r.get("so_val", 0) > 0 and r.get("cost_val", 0) > r["so_val"]:
                losses.append("%s (cost %s over contract)"
                              % (r["label"], _money_fmt(r["cost_val"] - r["so_val"], r["sym"])))
        token, count = _shared_token([r["label"] for r in uniq])
        pattern = (" Note: %d of them share '%s' — that looks like one root cause "
                   "(pricing or scoping), not %d separate accidents."
                   % (count, token, len(uniq)) if token else "")
        items.append(("red", "Loss-making projects",
                      "%d active projects run a margin under 20%%.%s%s"
                      % (len(uniq),
                         (" Cost already exceeds contract on: %s." % "; ".join(losses[:3]))
                         if losses else "", pattern)))
    falling = [(s["label"], n, txt) for s in squads
               for (t, n, txt) in s.get("proj_stories", [])
               if t == "red" and "DOWN" in txt]
    if falling:
        items.append(("red", "Margins in motion",
                      "Profitability fell this week on: %s. These are the ones to catch "
                      "BEFORE they join the loss-makers."
                      % ", ".join(sorted({n for _s, n, _t in falling})[:4])))
    stalled = sorted({n for s in squads for (t, n, txt) in s.get("proj_stories", [])
                      if "No work logged" in txt or "no work logged" in txt})
    if stalled:
        items.append(("amber", "Stalled projects",
                      "No time was logged last week on: %s. Either they are waiting on "
                      "customers (fine — say so) or they are quietly slipping."
                      % ", ".join(stalled[:5])))
    if org["sla_g10"]:
        top = org["sla_rows"][0] if org["sla_rows"] else None
        conc = ""
        if top and org["sla_g10"]:
            share = int(_fnum(top.get("dg10"))) / org["sla_g10"] * 100
            if share >= 33:
                conc = (" %s alone holds %d of the %d (%s%%) — that is one customer "
                        "relationship, not a process problem."
                        % (top["label"], int(_fnum(top.get("dg10"))), org["sla_g10"],
                           _h(share)))
        items.append(("red", "Support ageing",
                      "%d tickets are older than 10 working days; %d more sit on hold.%s"
                      % (org["sla_g10"], org["sla_hold"], conc)))
    weak_plan = [s for s in squads if s["d"]["plan_next"] < 75]
    if weak_plan:
        items.append(("amber", "Thin forward book",
                      "Next week is under-planned for %s — utilisation problems start in "
                      "the planning board."
                      % ", ".join("%s (%s%%)" % (s["label"], _h(s["d"]["plan_next"]))
                                  for s in weak_plan)))
    return items


def _md_email(week_label, org, squads, today, person_split=None, sinks=None):
    d = org
    cards = [
        _card("Pass rate", "%s%%" % _h(d["pass_rate"]), d["pass_measure"] + d["pass_wow"],
              _tone(d["pass_rate"])),
        _card("Coverage", "%s%%" % _h(d["coverage"]), d["cov_measure"] + d["cov_wow"],
              _tone(d["coverage"])),
        _card("Billability", "%s%%" % _h(d["bill"]),
              "target 75%% · 8-wk avg %s%%%s" % (_h(d["bill_avg"]), d["bill_wow"]),
              _tone(d["bill"], 75, 60)),
        _card("Next-week planning", "%s%%" % _h(d["plan_next"]), d["plan_next_label"],
              _tone(d["plan_next"], 75, 60)),
    ]
    attention = _md_attention(org, squads, today, sinks=sinks)
    red_rows, seen = [], set()
    for s in squads:
        for r in s["d"]["projects"]:
            if (r.get("tones", {}).get("prof_so") == "bad"
                    or r.get("tones", {}).get("prof_inv") == "bad") \
                    and r["label"] not in seen:
                seen.add(r["label"])
                red_rows.append(r)
    body = (
        "<p style='font-size:13px;color:#1e293b;'>Abhi, Ferry, Carel — operations last week "
        "(%s), across all three companies, in the time it takes to drink half a coffee.</p>"
        % escape(week_label)
        + _section("The week in one line",
                   "<p style='font-size:13.5px;line-height:1.55;color:#0f172a;'><b>%s</b></p>"
                   % escape(_md_headline(org, squads)))
        + _kpi_row(cards)
        + _section("What's working", _story_list(_md_working(org, squads, person_split)))
        + _section("What needs attention", _story_list(attention))
        + _section("Squad league table", _md_league(squads))
        + (_section("Projects to watch (margin under 20%)", _projects_table(red_rows))
           if red_rows else "")
        + _section("Support tickets ageing", _sla_block(d))
    )
    return _email_shell("Ops Weekly · MD Brief", week_label, body)


# ---------------------------------------------------------------------------
# The Odoo agent
# ---------------------------------------------------------------------------
class LinkederpDashboardOpsEmail(models.Model):
    _inherit = "linkederp.dashboard"

    @api.model
    def _ensure_packaged_dashboards(self):
        super()._ensure_packaged_dashboards()
        # Safe-by-default: until Akshay clears this parameter, every ops email
        # goes only to him with a [TEST] prefix.
        icp = self.env["ir.config_parameter"].sudo()
        if icp.get_param(OPS_EMAIL_TEST_PARAM) is False:
            icp.set_param(OPS_EMAIL_TEST_PARAM, OPS_EMAIL_TEST_DEFAULT)

    @api.model
    def _cron_ops_weekly_emails(self):
        self._ops_weekly_emails_send()

    @api.model
    def action_send_ops_weekly_emails(self, week=False):
        """Manual/validator trigger. `week` = any date in the week to report
        on (string or date); defaults to the last completed week."""
        return self._ops_weekly_emails_send(week=week, force=True)

    @api.model
    def _ops_weekly_emails_send(self, week=False, force=False):
        dashboard = self.sudo().search(
            [("name", "=", OPS_DASHBOARD_NAME), ("active", "=", True)], limit=1)
        if not dashboard:
            _logger.warning("Ops weekly emails: dashboard %r not found", OPS_DASHBOARD_NAME)
            return {"sent": 0, "reason": "dashboard not found"}
        dashboard = dashboard.sudo()

        if week:
            week_start = dashboard._ops_week_start(fields.Date.to_date(week))
        else:
            week_start = dashboard._ops_last_completed_week()
        week_key = fields.Date.to_string(week_start)
        week_label = dashboard._ops_week_label(week_start)
        today = fields.Date.context_today(dashboard)

        icp = self.env["ir.config_parameter"].sudo()
        test_to = (icp.get_param(OPS_EMAIL_TEST_PARAM) or "").strip()
        if not force and not test_to and icp.get_param(OPS_EMAIL_LAST_PARAM) == week_key:
            _logger.info("Ops weekly emails: %s already sent, skipping", week_key)
            return {"sent": 0, "reason": "already sent for %s" % week_key}

        # --- collect per-squad + org data from the dashboard's own engine ---
        org = _squad_payload_data(
            {"widgets": dashboard._ops_dashboard_widgets(filters={"week": week_key})})
        squads = []
        for team in dashboard._ops_subteam_options():
            if not team["value"]:
                continue
            widgets = dashboard._ops_dashboard_widgets(
                filters={"week": week_key, "ops_team": team["value"]})
            d = _squad_payload_data({"widgets": widgets})
            if not d["people"]:
                continue
            leads = dashboard._ops_lead_employees(team["value"])
            od_name = _dedupe_names([emp.name for emp in leads])
            od_emails = []
            for emp in leads:
                addr = (emp.work_email or (emp.user_id and emp.user_id.email) or "").strip()
                if addr and addr.lower() not in [a.lower() for a in od_emails]:
                    od_emails.append(addr)
            squads.append({"value": team["value"], "label": team["label"],
                           "od": od_name, "emails": od_emails, "d": d})

        # --- analysis layer: 3 read_groups over the timesheets -------------
        Line = self.env["account.analytic.line"].sudo().with_context(active_test=False)
        week_end = week_start + timedelta(days=6)

        def week_hours(monday, pids):
            rows = Line.read_group(
                [("project_id", "in", pids),
                 ("date", ">=", fields.Date.to_string(monday)),
                 ("date", "<=", fields.Date.to_string(monday + timedelta(days=6)))],
                ["unit_amount:sum"], ["project_id"], lazy=False)
            return {r["project_id"][0]: r.get("unit_amount") or 0.0
                    for r in rows if r.get("project_id")}

        pids = sorted({r["pid"] for s in squads for r in s["d"]["projects"]
                       if r.get("pid") is not None})
        hours_by_pid = {}
        if pids:
            h_last = week_hours(week_start, pids)
            h_prev = week_hours(week_start - timedelta(days=7), pids)
            hours_by_pid = {pid: (h_last.get(pid, 0.0), h_prev.get(pid, 0.0))
                            for pid in pids}

        ops_names = {p["name"] for s in squads for p in s["d"]["people"]}
        person_split, sinks = {}, {}
        for r in Line.read_group(
                [("project_id", "!=", False),
                 ("date", ">=", week_key),
                 ("date", "<=", fields.Date.to_string(week_end))],
                ["unit_amount:sum"],
                ["user_id", "project_id", "timesheet_invoice_type"], lazy=False):
            u, pj = r.get("user_id"), r.get("project_id")
            if not u or not pj or u[1] not in ops_names:
                continue
            hrs = r.get("unit_amount") or 0.0
            billable = (r.get("timesheet_invoice_type") or "") != "non_billable"
            slot = person_split.setdefault(u[1], {}).setdefault(pj[1], [0.0, 0.0])
            slot[0] += hrs
            if billable:
                slot[1] += hrs
            else:
                sinks[pj[1]] = sinks.get(pj[1], 0.0) + hrs

        for s in squads:
            s["ppl_stories"] = _people_stories(s["d"], person_split)
            s["proj_stories"] = _project_stories(s["d"], hours_by_pid, today)
            conc = _squad_concentration(s["d"]["people"], person_split)
            if conc:
                s["proj_stories"] = s["proj_stories"] + [conc]

        # --- render + send ---------------------------------------------------
        Mail = self.env["mail.mail"].sudo()
        mail_ids = []
        skipped = []

        def queue(subject, body, recipients):
            if test_to:
                recipients = [test_to]
                subject = "[TEST] " + subject
            if not recipients:
                skipped.append(subject)
                _logger.warning("Ops weekly emails: no recipients for %r, skipped", subject)
                return
            mail_ids.append(Mail.create({
                "subject": subject,
                "body_html": body,
                "email_to": ",".join(recipients),
                "auto_delete": False,
            }).id)

        for s in squads:
            queue("Ops Weekly — %s — %s" % (s["label"], week_label),
                  _od_email(s["label"], s["od"], week_label, s["d"],
                            s["ppl_stories"], s["proj_stories"]),
                  s["emails"])
        md_to = [a.strip() for a in (icp.get_param(OPS_EMAIL_MD_PARAM) or "").split(",")
                 if a.strip()]
        queue("Ops Weekly MD Brief — %s" % week_label,
              _md_email(week_label, org, squads, today, person_split, sinks),
              md_to)

        if mail_ids:
            Mail.browse(mail_ids).send(raise_exception=False)
        if not test_to:
            icp.set_param(OPS_EMAIL_LAST_PARAM, week_key)
        _logger.info("Ops weekly emails: %s — %d queued (%d squads), %d skipped, test=%s",
                     week_label, len(mail_ids), len(squads), len(skipped), bool(test_to))
        return {"sent": len(mail_ids), "mail_ids": mail_ids, "week": week_key,
                "week_label": week_label, "squads": [s["label"] for s in squads],
                "test_mode": bool(test_to), "skipped": skipped}
