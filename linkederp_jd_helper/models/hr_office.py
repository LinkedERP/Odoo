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
     "Making a new joiner's first days smooth: hiring approval, offer, documents, email and the first-week plan.",
     "fa-check-square-o", ("New joiners", "hr.applicant")),
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
            "onboarding": [
                ("hiring approvals waiting for you", "hr.applicant", [("x_offer_status", "=", "pending"), ("x_offer_approver_id", "=", uid)], True),
                ("hiring approvals sent back", "hr.applicant", [("x_hiring_status", "=", "selected"), ("x_offer_status", "=", "returned")], True),
                ("selected candidates to request approval for", "hr.applicant", [("x_hiring_status", "=", "selected"), ("x_offer_status", "in", ("draft", False))], False),
                ("approved, offer to send", "hr.applicant", [("x_hiring_status", "=", "selected"), ("x_offer_status", "=", "approved")], False),
            ],
        }
        tiles = []
        for key, name, manager, does, icon, target in TILES:
            action_id = self._action_id(*target) if target else False
            if key in self.AREAS:  # opens its own tiles page
                action_id = self.env.ref("linkederp_jd_helper.action_hr_%s" % key).id
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

    # Sub-pages of the HR Office: title, line under it, then tiles as
    # (key, name, what it does, icon, screen to open (action name, model), [(label, model, domain, needs someone?)])
    AREAS = {
        "recruitment": ("Recruitment", "Hiring requests, interviews, the HR box of new CVs and every profile we have.", [
            ("requests", "New requests", "Raise a hiring request or approve one.", "fa-file-text-o",
             ("Hiring Requests", "x_hiring_request"),
             [("hiring requests to approve", "x_hiring_request", [("x_status", "=", "submitted")], True),
              ("roles being hired", "x_hiring_request", [("x_status", "=", "in_progress")], False)]),
            ("interviews", "My interviews", "Interviews you are on the panel for, and your decisions.", "fa-comments-o",
             ("My interviews", "x_interview"),
             [("interviews waiting for your decision", "x_interview", [("x_up_next", "=", True), ("x_interviewer_ids", "in", "UID")], True)]),
            ("hrbox", "HR box", "New CVs for open roles: read by the AI, for HR to review.", "fa-inbox",
             ("Candidates (HR Office)", "hr.applicant"),
             [("new candidates to review", "hr.applicant", [("x_hiring_request_id", "!=", False), ("x_hiring_status", "=", "new")], True)]),
            ("profiles", "Profile database", "Every candidate profile we have, including past ones.", "fa-database",
             ("Profile database", "hr.applicant"),
             [("profiles", "hr.applicant", ["|", ("active", "=", True), ("active", "=", False)], False)]),
        ]),
        "referrals": ("Referrals", "Know someone good? Pick a role, read the JD and refer them.", [
            ("roles", "Open roles", "See the roles we are hiring for, read the JD and refer someone.", "fa-briefcase",
             ("Open roles", "x_hiring_request"), [("open roles", "x_hiring_request", [("x_status", "=", "in_progress")], False)]),
            ("mine", "My referrals", "People you referred, their status and their AI score.", "fa-heart",
             ("My referrals", "x_referral"), [("referrals sent", "x_referral", [("create_uid", "=", "UID")], False)]),
        ]),
    }

    @api.model
    def get_area(self, area):
        """Tiles for one HR Office sub-page, with the same live status lines as the home screen."""
        title, subtitle, rows = self.AREAS[area]
        tiles = []
        for key, name, does, icon, target, stats in rows:
            lines = []
            for label, model, domain, urgent in stats:
                domain = [(d[0], d[1], self.env.uid if d[2] == "UID" else d[2]) if isinstance(d, tuple) else d for d in domain]
                n = self._count(model, domain)
                if n is not None:
                    lines.append((label, n, urgent))
            badge = sum(n for _label, n, urgent in lines if urgent)
            first = next((l for l in lines if l[2] and l[1]), None) or next((l for l in lines if l[1]), None)
            action_id = self._action_id(*target)
            tiles.append({"key": key, "name": name, "manager": "", "does": does, "icon": icon,
                          "action_id": action_id, "built": bool(action_id), "badge": badge,
                          "status": _say(first[1], first[0]) if first else "All clear", "hot": bool(badge)})
        return {"title": title, "subtitle": subtitle, "tiles": tiles}
