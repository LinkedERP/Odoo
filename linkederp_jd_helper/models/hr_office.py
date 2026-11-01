# -*- coding: utf-8 -*-
"""HR Office home screen: one tile per HR area with a live one-line status.

Tiles map to the Studio-style screens built in this database (found by action name), so an area that is not
built yet simply shows as 'Coming soon'. Counts run as the current user, so everyone sees only what their
access allows (for example, concerns are counted only for the HR Manager role)."""
from odoo import api, models

# key, name, assistant, what it does (tile tooltip), icon, screen to open (action name, model) or None
TILES = [
    ("recruitment", "Recruitment", "Arjun",
     "Hiring the right people: requests, CVs read and scored by AI, interviews and panel decisions.",
     "fa-user-plus", ("Hiring Requests", "x_hiring_request")),
    ("admin", "Admin", "Ruby",
     "Office supplies, laptops and one-off asks as requests, plus the office lease and company documents.",
     "fa-briefcase", ("Admin Requests", "x_admin_request")),
    ("grievance", "Grievance", "Meera",
     "A private, safe place to raise a concern. Only the HR Manager reads them; people decide, never AI.",
     "fa-shield", ("Concerns", "x_grievance")),
    ("referrals", "Referrals", "Refer a friend", "Refer someone you know for an open role.",
     "fa-heart", ("Open roles", "x_hiring_request")),
    ("onboarding", "Onboarding", "Nisha",
     "Making a new joiner's first days smooth: documents, laptop, email and the first-week plan.", "fa-check-square-o", None),
    ("payroll", "Payroll", "Kabir", "Paying everyone correctly and on time, with PF, TDS and claims done right.", "fa-money", None),
    ("misc", "Surveys & Profiles", "Tara", "Employee profiles, pulse surveys and HR letters.", "fa-bar-chart", None),
]


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

    @api.model
    def get_overview(self):
        uid = self.env.uid
        # (label, model, domain, needs someone?) in the order the tile should mention them
        stats = {
            "recruitment": [
                ("hiring requests to approve", "x_hiring_request", [("x_status", "=", "submitted")], True),
                ("interviews waiting for your decision", "x_interview", [("x_up_next", "=", True), ("x_interviewer_ids", "in", uid)], True),
                ("new candidates to review", "hr.applicant", [("x_hiring_request_id", "!=", False), ("x_hiring_status", "=", "new")], True),
                ("roles being hired", "x_hiring_request", [("x_status", "=", "in_progress")], False),
            ],
            "admin": [
                ("admin requests to approve", "x_admin_request", [("x_stage", "=", "new")], True),
                ("approved, to buy", "x_admin_request", [("x_stage", "=", "approved")], False),
                ("bought, to hand over", "x_admin_request", [("x_stage", "=", "bought")], False),
            ],
            "grievance": [("open concerns", "x_grievance", [("x_stage", "!=", "closed")], True)],
            "referrals": [("open roles to refer for", "x_hiring_request", [("x_status", "=", "in_progress")], False)],
        }
        tiles = []
        for key, name, manager, does, icon, target in TILES:
            action_id = self._action_id(*target) if target else False
            lines = [(label, n, urgent) for label, model, domain, urgent in stats.get(key, [])
                     for n in [self._count(model, domain)] if n is not None]
            badge = sum(n for _label, n, urgent in lines if urgent)
            # status: the first thing that needs someone, else the first non-zero count
            first = next((l for l in lines if l[2] and l[1]), None) or next((l for l in lines if l[1]), None)
            status = _say(first[1], first[0]) if first else ("All clear" if lines else "Coming soon")
            tiles.append({"key": key, "name": name, "manager": manager, "does": does, "icon": icon,
                          "action_id": action_id, "built": bool(action_id), "badge": badge,
                          "status": status, "hot": bool(badge)})
        return {"tiles": tiles}
