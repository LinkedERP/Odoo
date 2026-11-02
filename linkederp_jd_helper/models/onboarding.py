# -*- coding: utf-8 -*-
"""Onboarding step 3: the joining form.

7 days before the joining date (or when HR clicks "Send joining form now") the candidate gets a private link
to /joining/<token>. What they fill goes on x_joining_form; the files go into a Documents folder for the joiner
(Employees / <name>). Until it is submitted, a reminder goes every 2 days and HR gets a "call the candidate" to-do.
x_joining_form and the hr.applicant x_ fields are Studio-style, so they are used through env at run time.
"""
import base64
import re
import uuid
from datetime import timedelta
from html import escape

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

MAX_FILE = 10 * 1024 * 1024
FILE_TYPES = (".pdf", ".jpg", ".jpeg", ".png")

# (key, label, required: True / False / "exp" = needed if they worked before, several files)
UPLOADS = [
    ("pan_copy", "PAN card", True, False),
    ("aadhaar_copy", "Aadhaar card (copy only, we do not record the number)", True, False),
    ("passport", "Passport (if you have one)", False, False),
    ("degree", "Highest degree certificate", True, False),
    ("relieving", "Relieving or experience letters", "exp", True),
    ("payslips", "Last 3 payslips", "exp", True),
    ("cheque", "Cancelled cheque or bank passbook", True, False),
    ("photo", "Passport-size photo", True, False),
]

# (field, label, required, input type)
FIELDS = [
    ("x_pan_name", "Full name as on PAN", True, "text"),
    ("x_dob", "Date of birth", True, "date"),
    ("x_gender", "Gender", True, "gender"),
    ("x_phone", "Phone", True, "tel"),
    ("x_email", "Personal email", True, "email"),
    ("x_blood_group", "Blood group", False, "text"),
    ("x_addr_current", "Current address", True, "area"),
    ("x_addr_permanent", "Permanent address", True, "area"),
    ("x_emg_name", "Emergency contact name", True, "text"),
    ("x_emg_relation", "Relation", True, "text"),
    ("x_emg_phone", "Emergency contact phone", True, "tel"),
    ("x_pan_number", "PAN number", True, "text"),
    ("x_uan", "UAN (only if you already have one)", False, "text"),
    ("x_bank_holder", "Account holder name", True, "text"),
    ("x_bank_account", "Account number", True, "text"),
    ("x_bank_ifsc", "IFSC code", True, "text"),
    ("x_bank_name", "Bank name", True, "text"),
]


def check_values(vals):
    """Return a list of problems with what the candidate typed (empty = fine)."""
    errors = []
    for name, label, required, _kind in FIELDS:
        if required and not vals.get(name):
            errors.append("%s is needed." % label)
    if vals.get("x_pan_number") and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", vals["x_pan_number"]):
        errors.append("PAN number should look like ABCDE1234F.")
    if vals.get("x_bank_ifsc") and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", vals["x_bank_ifsc"]):
        errors.append("IFSC code should look like HDFC0001234.")
    if vals.get("x_bank_account") and not re.fullmatch(r"[0-9]{9,18}", vals["x_bank_account"]):
        errors.append("Account number should be 9 to 18 digits.")
    if vals.get("x_uan") and not re.fullmatch(r"[0-9]{12}", vals["x_uan"]):
        errors.append("UAN should be 12 digits.")
    return errors


class LinkederpOnboarding(models.AbstractModel):
    _inherit = "linkederp.jd.helper"

    # ---------- send ----------
    @api.model
    def send_joining_form(self, applicant_ids):
        """Button 'Send joining form now' (and the 7-day job): create the form and email the private link."""
        for app in self.env["hr.applicant"].browse(applicant_ids):
            if app.x_offer_sign_state != "signed":
                raise UserError("The offer letter needs to be signed first.")
            if not app.email_from:
                raise UserError("The candidate has no email address.")
            form = app.x_joining_form_id
            if form.x_state == "submitted":
                raise UserError("The joining form is already submitted.")
            if not form:
                form = self.env["x_joining_form"].sudo().create({
                    "x_name": app.partner_name, "x_applicant_id": app.id, "x_token": uuid.uuid4().hex,
                    "x_state": "sent", "x_folder_id": self._joiner_folder(app).id,
                    "x_email": app.email_from, "x_phone": app.partner_phone})
                app.sudo().x_joining_form_id = form
            form.sudo().write({"x_sent_on": fields.Datetime.now()})
            self._mail_candidate(app, "Your joining form for LinkedERP", (
                "<p>Dear %s,</p><p>We look forward to you joining us on <b>%s</b>. Please fill in your joining form and "
                "upload your documents here (it takes about 10 minutes):</p><p><a href='%s'>Open my joining form</a></p>"
                "<p>Please do not send documents by email. The link is private to you.</p><p>HR team, LinkedERP India</p>")
                % (escape(app.partner_name.split(" ")[0]), app.x_offer_doj.strftime("%d %B %Y"), app.x_joining_link))
            app.message_post(body="Joining form sent to %s." % app.email_from)
        return True

    def _joiner_folder(self, app):
        """Employees / <name> in Documents, private to HR."""
        Doc = self.env["documents.document"].sudo()
        parent = Doc.search([("type", "=", "folder"), ("name", "=", "Employees"), ("folder_id", "=", False),
                             ("company_id", "=", app.company_id.id)], limit=1)
        return Doc.create({"type": "folder", "name": app.partner_name, "folder_id": parent.id or False,
                           "company_id": app.company_id.id, "access_internal": "none", "access_via_link": "none",
                           "owner_id": (app.user_id or self.env.user).id})

    def _mail_candidate(self, app, subject, body):
        partner = app.partner_id or self.env["res.partner"].sudo().create(
            {"name": app.partner_name, "email": app.email_from, "phone": app.partner_phone})
        app.message_post(subject=subject, body=Markup(body),
                         partner_ids=[partner.id], message_type="comment", subtype_xmlid="mail.mt_comment")

    # ---------- daily job ----------
    @api.model
    def _cron_joining_forms(self):
        today = fields.Date.context_today(self)
        due = self.env["hr.applicant"].search([
            ("x_offer_sign_state", "=", "signed"), ("x_joining_form_id", "=", False),
            ("x_offer_doj", ">=", today), ("x_offer_doj", "<=", today + timedelta(days=7))])
        for app in due:
            self.send_joining_form(app.ids)
        for form in self.env["x_joining_form"].sudo().search([("x_state", "=", "sent")]):
            app = form.x_applicant_id
            last = form.x_last_reminder or (form.x_sent_on and form.x_sent_on.date())
            if not app or not last or (today - last).days < 2 or (app.x_offer_doj and app.x_offer_doj < today):
                continue
            self._mail_candidate(app, "Reminder: your LinkedERP joining form", (
                "<p>Dear %s,</p><p>A gentle reminder to fill in your joining form before you join on <b>%s</b>:</p>"
                "<p><a href='%s'>Open my joining form</a></p><p>HR team, LinkedERP India</p>")
                % (escape(app.partner_name.split(" ")[0]), app.x_offer_doj.strftime("%d %B %Y"), app.x_joining_link))
            form.write({"x_last_reminder": today, "x_reminders": form.x_reminders + 1})
            summary = "Call %s: joining form not filled" % app.partner_name
            if not app.activity_ids.filtered(lambda a: a.summary == summary):
                app.activity_schedule("mail.mail_activity_data_todo", summary=summary,
                                      user_id=(app.user_id or self.env.ref("base.user_admin")).id)

    # ---------- save (called by the /joining controller, as superuser, after the token check) ----------
    @api.model
    def save_joining_form(self, form, vals, files, worked):
        """vals: typed values; files: {key: [FileStorage]}; worked: True/False/None (not answered).
        Returns a list of problems (empty = saved)."""
        errors = check_values(vals)
        if worked is None:
            errors.append("Please say whether you have worked before.")
        for key, label, required, _many in UPLOADS:
            for f in files.get(key, []):
                if not f.filename.lower().endswith(FILE_TYPES):
                    errors.append("%s: please upload a PDF, JPG or PNG." % label)
            if (required is True or (required == "exp" and worked)) and not files.get(key):
                errors.append("%s is needed." % label)
        if errors:
            return errors
        vals = dict(vals, x_worked_before=worked)
        app = form.x_applicant_id
        docs = self.env["documents.document"]
        for key, label, _required, _many in UPLOADS:
            for i, f in enumerate(files.get(key, []), 1):
                data = f.read()
                if len(data) > MAX_FILE:
                    return ["%s is bigger than 10 MB. Please upload a smaller file." % label]
                ext = f.filename.rsplit(".", 1)[-1].lower()
                name = "%s - %s%s.%s" % (label.split(" (")[0], app.partner_name, " (%s)" % i if i > 1 else "", ext)
                att = self.env["ir.attachment"].create({"name": name, "datas": base64.b64encode(data),
                                                        "res_model": "hr.applicant", "res_id": app.id})
                docs |= self.env["documents.document"].create({"attachment_id": att.id, "folder_id": form.x_folder_id.id,
                                                              "owner_id": form.x_folder_id.owner_id.id})
        form.write(dict({k: v or False for k, v in vals.items()}, x_state="submitted", x_submitted_on=fields.Datetime.now(),
                        x_document_ids=[(4, d.id) for d in docs]))
        app.activity_ids.filtered(lambda a: a.summary and a.summary.startswith("Call %s" % app.partner_name)).action_done()
        app.message_post(body="Joining form submitted by the candidate, with %s document(s) saved in Documents." % len(docs))
        return []
