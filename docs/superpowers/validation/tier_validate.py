# Odoo Partnership Tier dashboard — validator (2026-07-21).
# Independent JSON-RPC recounts of the tier numbers + payload regression.
# Env: ODOO_URL, ODOO_DB (or auto), ODOO_USERNAME, ODOO_PASSWORD.
import json
import os
import sys
import urllib.request
from datetime import date

URL = os.environ.get("ODOO_URL", "https://linkederp-dev.odoo.com")
DB = os.environ.get("ODOO_DB", "auto")
USERNAME = os.environ.get("ODOO_USERNAME", "akshay@linkederp.com")
PASSWORD = os.environ.get("ODOO_PASSWORD", "")
# Minimum version carrying the tier dashboard + cursor fix. ">=" not "=="
# because a parallel session also pushes this module (e.g. 19.0.1.20.0).
MIN_VERSION = (19, 0, 1, 21, 0)
_rid = [0]
CHECKS = []


def rpc(service, method, *args):
    _rid[0] += 1
    payload = json.dumps({"jsonrpc": "2.0", "method": "call", "id": _rid[0],
                          "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(URL + "/jsonrpc", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        out = json.loads(resp.read().decode())
    if out.get("error"):
        raise RuntimeError(json.dumps(out["error"])[:1500])
    return out.get("result")


def check(label, ok, detail=""):
    CHECKS.append(ok)
    print("%-4s %s %s" % ("PASS" if ok else "FAIL", label, ("— %s" % detail) if detail else ""))


def month_start(d):
    return date(d.year, d.month, 1)


def month_index(d):
    return d.year * 12 + d.month


def main():
    global DB
    if not PASSWORD:
        sys.exit("Set ODOO_PASSWORD")
    if DB == "auto":
        req = urllib.request.Request(URL + "/web/database/list",
                                     data=json.dumps({"jsonrpc": "2.0", "method": "call",
                                                      "params": {}, "id": 1}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            DB = json.loads(resp.read().decode())["result"][0]
        print("db:", DB)
    uid = rpc("common", "authenticate", DB, USERNAME, PASSWORD, {})

    def ex(model, method, args, kwargs=None):
        return rpc("object", "execute_kw", DB, uid, PASSWORD, model, method, args, kwargs or {})

    ver = ex("ir.module.module", "search_read",
             [[("name", "=", "linkederp_dashboard_studio")]], {"fields": ["installed_version"]})[0]
    ver_tuple = tuple(int(x) for x in ver["installed_version"].split("."))
    check("module version >= %s" % ".".join(map(str, MIN_VERSION)),
          ver_tuple >= MIN_VERSION, ver["installed_version"])

    check("sale.order has odoo_renewal_outcome",
          "odoo_renewal_outcome" in ex("sale.order", "fields_get", [[]], {"attributes": ["type"]}))

    # Payload (creates the record via the ensure chain on first call).
    dash = ex("linkederp.dashboard", "search_read",
              [[("name", "=", "Odoo Partnership Tier")]],
              {"fields": ["id", "bucket", "sequence"]})
    if not dash:
        ex("linkederp.dashboard", "get_dashboard_payload", [False, False, False, {}])
        dash = ex("linkederp.dashboard", "search_read",
                  [[("name", "=", "Odoo Partnership Tier")]],
                  {"fields": ["id", "bucket", "sequence"]})
    check("dashboard record exists", bool(dash))
    check("bucket = management", dash and dash[0]["bucket"] == "management",
          str(dash and dash[0]["bucket"]))
    payload = ex("linkederp.dashboard", "get_dashboard_payload",
                 [dash[0]["id"], False, False, {}])
    widgets = {w["id"]: w for w in payload.get("widgets") or []}
    expected_ids = {"tier_users", "tier_consultants", "tier_retention",
                    "tier_standing", "tier_trend", "tier_company_stack",
                    "tier_co_0", "tier_co_1", "tier_co_2",
                    "tier_q_users", "tier_arr_group", "tier_arr_in",
                    "tier_arr_idza", "tier_pipeline", "tier_rolloff",
                    "tier_reviews"}
    check("all 16 mockup widgets present", expected_ids <= set(widgets),
          str(sorted(expected_ids - set(widgets))))
    check("banner is bad/warn when present",
          "tier_banner" not in widgets
          or widgets["tier_banner"].get("sev") in ("bad", "warn"))
    check("mockup widget types",
          (widgets.get("tier_trend") or {}).get("type") == "tierline"
          and (widgets.get("tier_company_stack") or {}).get("type") == "tierstack"
          and (widgets.get("tier_co_0") or {}).get("type") == "tiercompany"
          and (widgets.get("tier_reviews") or {}).get("type") == "qtiles")
    check("criteria cards carry chips",
          all((widgets.get(i) or {}).get("chips")
              for i in ("tier_users", "tier_consultants", "tier_retention",
                        "tier_standing")))
    check("no widget errors", all(not w.get("error") for w in widgets.values()))
    check("info on all tier widgets",
          all((widgets[i].get("info") or "").strip() for i in expected_ids if i in widgets))

    # ---- independent trailing-12m recount ----
    today = date.today()
    this_m = month_start(today)
    leads = ex("crm.lead", "search_read",
               [[("stage_id.is_won", "=", True), ("x_studio_no_of_users", ">", 0)]],
               {"fields": ["x_studio_no_of_users", "date_closed", "company_id",
                           "expected_revenue"],
                "context": {"active_test": False}})
    cohorts = []
    for lead in leads:
        if not lead.get("date_closed"):
            continue
        closed = date(*[int(x) for x in lead["date_closed"][:10].split("-")])
        cohorts.append((month_start(closed), lead["x_studio_no_of_users"]))
    internal_raw = ex("ir.config_parameter", "get_param",
                      ["linkederp_dashboard.tier_internal_cohorts", "[]"])
    try:
        for row in json.loads(internal_raw or "[]"):
            cohorts.append((date(*[int(x) for x in row["month"].split("-")], 1)
                            if row["month"].count("-") == 1 else None,
                            int(row["users"])))
    except Exception:
        pass
    cohorts = [(m, u) for m, u in cohorts if m]

    def trailing(month):
        return sum(u for m, u in cohorts
                   if 0 <= month_index(month) - month_index(m) < 12)

    expect_now = trailing(this_m)
    w = widgets.get("tier_users") or {}
    check("trailing-12m recount", int(w.get("value") or 0) == expect_now,
          "widget %s vs recount %s" % (w.get("value"), expect_now))

    # company stack sums to trailing
    stack = widgets.get("tier_company_stack") or {}
    stack_sum = sum(int(p["value"]) for p in stack.get("points") or [])
    check("company stack sums to trailing", stack_sum == expect_now,
          "%s vs %s" % (stack_sum, expect_now))

    # tierline: current month actual == trailing; series split around now
    trend = widgets.get("tier_trend") or {}
    pts = trend.get("points") or []
    now_pt = next((p for p in pts if p.get("now")), None)
    check("tierline has a now point", bool(now_pt))
    check("tierline now actual == trailing == committed",
          now_pt and now_pt.get("actual") == expect_now
          and now_pt.get("committed") == expect_now,
          "%s / %s vs %s" % (now_pt and now_pt.get("actual"),
                             now_pt and now_pt.get("committed"), expect_now))
    now_idx = pts.index(now_pt) if now_pt else -1
    check("tierline past months have actual only",
          now_idx >= 0 and all(
              p.get("actual") is not None and p.get("committed") is None
              and p.get("forecast") is None for p in pts[:now_idx]))
    check("tierline future months have no actual",
          now_idx >= 0 and all(p.get("actual") is None for p in pts[now_idx + 1:]))
    check("tierline forecast >= committed in the future",
          now_idx >= 0 and all(
              (p.get("forecast") or 0) >= (p.get("committed") or 0)
              for p in pts[now_idx + 1:]))

    # pipeline recount
    pipe = ex("crm.lead", "search_count",
              [[("type", "=", "opportunity"), ("active", "=", True),
                ("stage_id.is_won", "=", False),
                ("x_studio_expected_user_license", ">", 0)]])
    prows = (widgets.get("tier_pipeline") or {}).get("rows") or []
    check("pipeline matrix rows == open forecast deals", len(prows) == pipe,
          "%s vs %s" % (len(prows), pipe))

    # review tiles
    rrows = (widgets.get("tier_reviews") or {}).get("points") or []
    check("4 review tiles", len(rrows) == 4, str([r["label"] for r in rrows]))
    check("reviews on SA quarter starts",
          all(r["label"].split()[1] in ("Feb", "May", "Aug", "Nov") for r in rrows),
          str([r["label"] for r in rrows]))

    # ARR: India card + combined ID+SA card sum <= group kpi (Other-company residue allowed)
    group = (widgets.get("tier_arr_group") or {}).get("value") or 0.0
    parts = ((widgets.get("tier_arr_in") or {}).get("value") or 0.0) + \
        ((widgets.get("tier_arr_idza") or {}).get("value") or 0.0)
    check("India + (Indonesia+SA) ARR sums <= group ARR",
          parts <= group + 0.01,
          "parts %.0f vs group %.0f" % (parts, group))

    # regression: every dashboard error-free
    boards = ex("linkederp.dashboard", "search_read", [[]], {"fields": ["id", "name"]})
    bad = []
    for board in boards:
        try:
            pl = ex("linkederp.dashboard", "get_dashboard_payload", [board["id"], False, False, {}])
            if any(wg.get("error") for wg in pl.get("widgets") or []):
                bad.append(board["name"])
        except Exception as exc:
            bad.append("%s (%s)" % (board["name"], str(exc)[:90]))
    check("regression: %d dashboards error-free" % len(boards), not bad, str(bad))

    passed = sum(1 for c in CHECKS if c)
    print("\n%d/%d checks passed" % (passed, len(CHECKS)))
    sys.exit(0 if passed == len(CHECKS) else 1)


if __name__ == "__main__":
    main()
