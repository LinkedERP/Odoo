# -*- coding: utf-8 -*-
"""Hero Profiles: a one-page consultant profile we send customers (Surveys & Profiles room).

The consultant fills it in, their manager (or HR) approves it, and only the APPROVED copy is ever printed:
approving freezes a hidden copy (is_snapshot), so later edits wait for the next approval.
The customer page never shows weak spots: skills below Proficient are hidden, and juniors get no career list.
"""
from datetime import date, timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

LEVELS = [("novice", "Novice"), ("beginner", "Beginner"), ("competent", "Competent"),
          ("proficient", "Proficient"), ("expert", "Expert")]
LANG_LEVELS = [("elementary", "Elementary"), ("limited", "Limited"), ("professional", "Professional"),
               ("full", "Full professional"), ("native", "Native / bilingual")]
KINDS = [("strength", "Strongest at"), ("proud", "Proud of"), ("skill", "Skill"), ("language", "Language"),
         ("certification", "Certification"), ("education", "Education"), ("project", "Selected work")]
REFRESH_DAYS = 180
SENIOR_MONTHS = 36  # 3+ years: career list on the page; less: the "your project team" panel instead


class HeroPlatform(models.Model):
    _name = "linkederp.hero.platform"
    _description = "Hero profile platform"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer()


class HeroJob(models.Model):
    _name = "linkederp.hero.job"
    _description = "Hero profile work history"
    _order = "date_from desc"

    profile_id = fields.Many2one("linkederp.hero.profile", required=True, ondelete="cascade")
    title = fields.Char(required=True)
    company = fields.Char(required=True)
    date_from = fields.Date("From", required=True)
    date_to = fields.Date("To", help="Leave empty if this is the current job.")
    detail = fields.Text("What you did")


class HeroLine(models.Model):
    _name = "linkederp.hero.line"
    _description = "Hero profile line"
    _order = "sequence, id"

    profile_id = fields.Many2one("linkederp.hero.profile", required=True, ondelete="cascade")
    kind = fields.Selection(KINDS, required=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    detail = fields.Text()
    level = fields.Selection(LEVELS)
    lang_level = fields.Selection(LANG_LEVELS, "Level ")
    year = fields.Char()
    platform_id = fields.Many2one("linkederp.hero.platform")
    part = fields.Char("Your part")
    file = fields.Binary("Certificate", attachment=True)
    file_name = fields.Char()


class HeroProfile(models.Model):
    _name = "linkederp.hero.profile"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Hero profile"
    _order = "name"

    active = fields.Boolean(default=True)
    is_snapshot = fields.Boolean(readonly=True, copy=False)
    snapshot_id = fields.Many2one("linkederp.hero.profile", "Approved copy", readonly=True, copy=False)
    employee_id = fields.Many2one("hr.employee", required=True, ondelete="cascade")
    name = fields.Char(compute="_compute_name", store=True)
    user_id = fields.Many2one(related="employee_id.user_id", store=True)
    reviewer_id = fields.Many2one("res.users", "Reviewer", compute="_compute_reviewer", store=True, readonly=False,
                                  help="Their manager. HR can also approve.")
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    image = fields.Image(related="employee_id.image_512")
    job_title = fields.Char("Title on the profile")
    location = fields.Char("Based in")
    time_zone = fields.Char(help="For example: IST, overlaps EU mornings")
    platform_ids = fields.Many2many("linkederp.hero.platform", string="Platforms")
    headline = fields.Char("One-line strength", tracking=True)
    summary = fields.Text()
    job_ids = fields.One2many("linkederp.hero.job", "profile_id", "Work history", copy=True)
    line_ids = fields.One2many("linkederp.hero.line", "profile_id", copy=True)
    strength_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "strength")])
    proud_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "proud")])
    skill_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "skill")])
    language_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "language")])
    certification_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "certification")])
    education_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "education")])
    project_ids = fields.One2many("linkederp.hero.line", "profile_id", domain=[("kind", "=", "project")])
    total_months = fields.Integer(compute="_compute_experience", store=True)
    total_experience = fields.Char(compute="_compute_experience", store=True)
    state = fields.Selection([("draft", "Draft"), ("review", "Waiting for review"), ("approved", "Approved"),
                              ("changes", "Changed since approval")], default="draft", required=True, tracking=True,
                             copy=False)
    review_note = fields.Text("Reviewer's comment", tracking=True)
    submitted_on = fields.Date(readonly=True, copy=False)
    approved_on = fields.Date(readonly=True, copy=False)
    approved_by = fields.Many2one("res.users", readonly=True, copy=False)
    needs_refresh = fields.Boolean(compute="_compute_needs_refresh", search="_search_needs_refresh")

    # ---------- computes ----------
    @api.depends("employee_id.name")
    def _compute_name(self):
        for p in self:  # "Deepa Kalmath (IN)" -> "Deepa Kalmath"
            name = p.employee_id.name or ""
            p.name = name.rsplit(" (", 1)[0] if name.endswith(")") else name

    @api.depends("employee_id.parent_id.user_id")
    def _compute_reviewer(self):
        for p in self:
            p.reviewer_id = p.employee_id.parent_id.user_id

    @api.depends("job_ids.date_from", "job_ids.date_to")
    def _compute_experience(self):
        today = date.today()
        for p in self:
            spans = sorted((j.date_from, j.date_to or today) for j in p.job_ids if j.date_from)
            days, end = 0, None
            for start, stop in spans:  # overlapping jobs count once
                start = max(start, end) if end else start
                if stop > start:
                    days += (stop - start).days
                end = max(stop, end) if end else stop
            p.total_months = round(days / 30.44)
            p.total_experience = experience_text(p.total_months)

    def _compute_needs_refresh(self):
        limit = date.today() - timedelta(days=REFRESH_DAYS)
        for p in self:
            p.needs_refresh = bool(p.approved_on and p.approved_on <= limit)

    def _search_needs_refresh(self, operator, value):
        limit = date.today() - timedelta(days=REFRESH_DAYS)
        return [("approved_on", "<=", limit)] if bool(value) == (operator == "=") else \
            ["|", ("approved_on", "=", False), ("approved_on", ">", limit)]

    # ---------- edits after approval ----------
    QUIET = {"state", "review_note", "snapshot_id", "submitted_on", "approved_on", "approved_by", "reviewer_id",
             "active", "is_snapshot"}

    def write(self, vals):
        res = super().write(vals)
        if set(vals) - self.QUIET and not any(k.startswith(("message_", "activity_")) for k in vals):
            self.filtered(lambda p: p.state == "approved" and not p.is_snapshot).write({"state": "changes"})
        return res

    # ---------- buttons ----------
    @api.model
    def action_open_my_profile(self):
        profile = self.search([("user_id", "=", self.env.uid), ("is_snapshot", "=", False)], limit=1)
        if not profile:
            emp = self.env.user.employee_id
            if not emp:
                raise UserError("Your user is not linked to an employee. Please ask HR.")
            profile = self.create({"employee_id": emp.id, "job_title": emp.job_title,
                                   "location": emp.private_city or emp.work_location_id.name})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": profile.id,
                "views": [(False, "form")], "name": "My Hero Profile"}

    def action_submit(self):
        for p in self:
            missing = [label for label, ok in [("One-line strength", p.headline), ("Summary", p.summary),
                                               ("Work history", p.job_ids), ("Strongest at", p.strength_ids)] if not ok]
            if missing:
                raise UserError("Please fill in before sending for review: %s." % ", ".join(missing))
            p.write({"state": "review", "submitted_on": date.today(), "review_note": False})
            reviewer = p.reviewer_id or self.env.ref("base.user_admin")
            p.activity_schedule("mail.mail_activity_data_todo", user_id=reviewer.id,
                                summary="Review the hero profile of %s" % p.name)
        return True

    def _can_review(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group("hr.group_hr_manager"):
            return True
        return user != self.user_id and (user == self.reviewer_id or user.has_group("hr.group_hr_user"))

    def action_approve(self):
        for p in self:
            if not p._can_review():
                raise UserError("Only %s's manager or HR can approve this profile." % p.name)
            old = p.snapshot_id
            copy = p.copy({"is_snapshot": True, "active": False, "state": "approved", "approved_on": date.today()})
            p.write({"state": "approved", "snapshot_id": copy.id, "approved_on": date.today(),
                     "approved_by": self.env.uid, "review_note": False})
            old.sudo().unlink()  # reviewers may not delete; the old frozen copy is ours to replace
            p.activity_ids.filtered(lambda a: a.summary and a.summary.startswith(("Review the hero", "Update your hero",
                                                                                  "Refresh your hero"))).action_done()
            p.message_post(body=Markup("Approved. This version is now the one customers receive."))
        return True

    def action_send_back(self):
        for p in self:
            if not p._can_review():
                raise UserError("Only %s's manager or HR can send this profile back." % p.name)
            if not p.review_note:
                raise UserError("Please write what to change in \"Reviewer's comment\" first.")
            p.write({"state": "draft"})
            p.activity_ids.filtered(lambda a: a.summary and a.summary.startswith("Review the hero")).action_done()
            if p.user_id:
                p.activity_schedule("mail.mail_activity_data_todo", user_id=p.user_id.id,
                                    summary="Update your hero profile", note=p.review_note)
        return True

    def action_print_wizard(self):
        return {"type": "ir.actions.act_window", "res_model": "linkederp.hero.print", "view_mode": "form",
                "target": "new", "name": "Print for a customer",
                "context": {"default_profile_ids": [(6, 0, self.ids)]}}

    # ---------- what the customer page shows ----------
    def _page_skills(self):
        return self.skill_ids.filtered(lambda s: s.level in ("proficient", "expert")).sorted(
            lambda s: (s.level != "expert", s.sequence))

    def _page_facts(self):
        langs = ", ".join(self.language_ids.mapped("name"))
        return [("Total experience", self.total_experience or "-", ""),
                ("Platforms", ", ".join(self.platform_ids.mapped("name")) or "-", ""),
                ("Based in", self.location or "-", self.time_zone or ""),
                ("Speaks", langs or "-", "")]

    # ---------- 6-monthly reminder ----------
    @api.model
    def _cron_refresh_reminders(self):
        for p in self.search([("state", "=", "approved"), ("needs_refresh", "=", True), ("user_id", "!=", False)]):
            if not p.activity_ids.filtered(lambda a: a.summary == "Refresh your hero profile"):
                p.activity_schedule("mail.mail_activity_data_todo", user_id=p.user_id.id,
                                    summary="Refresh your hero profile",
                                    note="It is 6 months since your profile was approved. Please add new work and certificates.")


def experience_text(months):
    if not months:
        return ""
    if months < 12:
        return "%d month%s" % (months, "" if months == 1 else "s")
    years = round(months / 6) / 2  # nearest half year
    return "%g years" % years if years != 1 else "1 year"


class HeroPrint(models.TransientModel):
    _name = "linkederp.hero.print"
    _description = "Print hero profiles for a customer"

    profile_ids = fields.Many2many("linkederp.hero.profile", string="Consultants", required=True,
                                   domain=[("is_snapshot", "=", False), ("snapshot_id", "!=", False)])
    customer = fields.Char("Prepared for", required=True, help="The customer's name, shown on each page.")
    note = fields.Text("Why this team (optional)", help="One or two lines shown on every page.")

    def action_print(self):
        not_ready = self.profile_ids.filtered(lambda p: not p.snapshot_id)
        if not_ready:
            raise UserError("Not approved yet: %s. Only approved profiles can go to customers."
                            % ", ".join(not_ready.mapped("name")))
        snaps = self.profile_ids.mapped("snapshot_id")
        return self.env.ref("linkederp_jd_helper.report_hero_profile").report_action(
            snaps.ids, data={"customer": self.customer, "note": self.note or ""})


assert experience_text(0) == "" and experience_text(8) == "8 months" and experience_text(12) == "1 year"
assert experience_text(65) == "5.5 years" and experience_text(24) == "2 years"
