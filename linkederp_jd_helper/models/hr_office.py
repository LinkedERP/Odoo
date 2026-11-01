# -*- coding: utf-8 -*-
"""HR Office home screen: the pixel office with one clickable room per HR area and live counts.

Rooms map to the Studio-style screens built in this database (found by action name), so a room that is not
built yet simply shows as 'Coming soon'. Counts run as the current user, so everyone sees only what their
access allows (for example, concerns are counted only for the HR Manager role)."""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# box = [left, top, right, bottom] in picture pixels (1344 x 752)
ROOMS = [
    ("reception", "Reception", "Maria", "HR Manager", [45, 500, 1300, 738],
     "The front door of HR. Maria keeps an eye on every room and tells the Office Head what needs attention.",
     ("Hiring Requests", "x_hiring_request")),
    ("recruitment", "Recruitment", "Arjun", "Room manager", [55, 15, 450, 258],
     "Hiring the right people: requests, CVs read and scored by AI, interviews and panel decisions.",
     ("Hiring Requests", "x_hiring_request")),
    ("onboarding", "Onboarding", "Nisha", "Room manager", [475, 15, 866, 258],
     "Making a new joiner's first days smooth: documents, laptop, email and the first-week plan.", None),
    ("payroll", "Payroll", "Kabir", "Room manager", [890, 15, 1286, 258],
     "Paying everyone correctly and on time, with PF, TDS and claims done right.", None),
    ("admin", "Admin", "Ruby", "Room manager", [55, 275, 450, 498],
     "Office supplies, laptops and one-off asks as requests, plus the office lease and company documents.",
     ("Admin Requests", "x_admin_request")),
    ("grievance", "Grievance", "Meera", "Room manager", [475, 275, 866, 498],
     "A private, safe place to raise a concern. Only the HR Manager reads them; people decide, never AI.",
     ("Concerns", "x_grievance")),
    ("misc", "Surveys & Profiles", "Tara", "Room manager", [890, 275, 1286, 498],
     "Employee profiles, pulse surveys and HR letters.", None),
    ("referrals", "Referrals", "Refer a friend", "Everyone", None,
     "Refer someone you know for an open role.", ("Open roles", "x_hiring_request")),
]
# tile order on the desk view (reception is the desk itself, so it has no tile)
TILES = ["recruitment", "admin", "grievance", "referrals", "onboarding", "payroll", "misc"]
ICONS = {"recruitment": "fa-user-plus", "admin": "fa-briefcase", "grievance": "fa-shield", "referrals": "fa-heart",
         "onboarding": "fa-check-square-o", "payroll": "fa-money", "misc": "fa-bar-chart"}


def _say(n, label):
    """'1' + 'roles being hired' -> '1 role being hired' (each label has one plural noun)."""
    if n == 1:
        words = label.split(" ")
        i = next((i for i, w in enumerate(words) if w.endswith("s") and len(w) > 3), None)
        if i is not None:
            words[i] = words[i][:-1]
        label = " ".join(words)
    return "%s %s" % (n, label)


class LinkederpHrOffice(models.AbstractModel):
    _name = "linkederp.hr.office"
    _description = "LinkedERP HR Office home screen"

    def _action_id(self, name, model):
        act = self.env["ir.actions.act_window"].sudo().search([("name", "=", name), ("res_model", "=", model)], limit=1)
        return act.id or False

    def _count(self, model, domain):
        if model not in self.env:
            return None
        try:
            return self.env[model].search_count(domain)
        except Exception:  # no access for this user: show nothing rather than an error
            return None

    def _todo(self, label, model, domain, count, view="list"):
        return {"label": label, "count": count, "action": {
            "type": "ir.actions.act_window", "name": label, "res_model": model, "domain": domain,
            "views": [[False, view], [False, "form"]], "target": "current"}}

    @api.model
    def get_overview(self):
        uid = self.env.uid
        stats = {
            "reception": [("hiring requests to approve", "x_hiring_request", [("x_status", "=", "submitted")], "list")],
            "recruitment": [
                ("interviews waiting for your decision", "x_interview", [("x_up_next", "=", True), ("x_interviewer_ids", "in", uid)], "list"),
                ("new candidates to review", "hr.applicant", [("x_hiring_request_id", "!=", False), ("x_hiring_status", "=", "new")], "kanban"),
                ("roles being hired", "x_hiring_request", [("x_status", "=", "in_progress")], "list"),
            ],
            "admin": [
                ("admin requests to approve", "x_admin_request", [("x_stage", "=", "new")], "kanban"),
                ("approved, to buy", "x_admin_request", [("x_stage", "=", "approved")], "kanban"),
                ("bought, to hand over", "x_admin_request", [("x_stage", "=", "bought")], "kanban"),
            ],
            "grievance": [("open concerns", "x_grievance", [("x_stage", "!=", "closed")], "kanban")],
            "referrals": [("open roles to refer for", "x_hiring_request", [("x_status", "=", "in_progress")], "list")],
        }
        # what counts as 'needs you' (shown on the badge and in the side list)
        urgent = {"hiring requests to approve", "interviews waiting for your decision", "new candidates to review",
                  "admin requests to approve", "open concerns"}
        rooms, todo = [], []
        for key, name, manager, role, box, does, target in ROOMS:
            action_id = self._action_id(*target) if target else False
            lines, badge = [], 0
            for label, model, domain, view in stats.get(key, []):
                n = self._count(model, domain)
                if n is None:
                    continue
                item = self._todo(label, model, domain, n, view)
                lines.append(item)
                if label in urgent and n:
                    badge += n
                    if not any(t["label"] == label for t in todo):
                        todo.append(dict(item, room=name))
            # one-line status for the tile: the first thing that needs someone, else the first non-zero count
            first = next((l for l in lines if l["label"] in urgent and l["count"]), None)                 or next((l for l in lines if l["count"]), None)
            status = _say(first["count"], first["label"]) if first else ("All clear" if lines else "Coming soon")
            rooms.append({"key": key, "name": name, "manager": manager, "role": role, "box": box, "does": does,
                          "action_id": action_id, "built": bool(action_id), "lines": lines, "badge": badge,
                          "status": status, "hot": bool(badge), "icon": ICONS.get(key, "fa-circle")})
        order = {k: i for i, k in enumerate(TILES)}
        tiles = sorted([r for r in rooms if r["key"] in order], key=lambda r: order[r["key"]])
        return {"rooms": [r for r in rooms if r["box"]], "tiles": tiles, "todo": todo, "user": self.env.user.name}
