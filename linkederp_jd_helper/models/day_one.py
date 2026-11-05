# -*- coding: utf-8 -*-
"""Onboarding day 1: HR clicks "Confirm joined" on the candidate.

Creates the employee, then the Microsoft 365 account and the Odoo login with that work email, the salary bank account (Linda gets a link and a to-do, never the numbers),
posts the team welcome in #general, and sends India joiners PF Form 11 (+ the UAN guide when they have no UAN)
with a to-do for HR to collect it back.
"""
import base64
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import file_open


class LinkederpDayOne(models.AbstractModel):
    _inherit = "linkederp.jd.helper"

    @api.model
    def confirm_joined(self, applicant_ids):
        today = fields.Date.context_today(self)
        for app in self.env["hr.applicant"].browse(applicant_ids):
            form = app.x_joining_form_id
            if app.employee_id:
                raise UserError("%s is already confirmed as joined." % app.partner_name)
            if form.x_state != "submitted":
                raise UserError("The joining form is not submitted yet. Please follow up with the candidate first.")
            if not app.x_offer_doj or app.x_offer_doj > today:
                raise UserError("The joining date is %s. Confirm on the day the candidate joins."
                                % (app.x_offer_doj and app.x_offer_doj.strftime("%d %b %Y")))
            emp = self._create_employee(app, form)
            acc = self._add_bank_account(emp, form)
            self._tell_linda(emp, acc)
            self._announce(emp)
            self._send_pf_pack(app, form)
            app.sudo().write({"employee_id": emp.id, "date_closed": fields.Datetime.now()})
            app.message_post(body=Markup("Joined on %s. Employee created; Linda asked to add the bank "
                                         "account; team welcome posted; PF Form 11%s sent.")
                             % (today.strftime("%d %b %Y"), "" if form.x_uan else " and UAN guide"))
            try:
                with self.env.cr.savepoint():
                    self.create_work_account(app.ids)
            except UserError as e:  # joining stays done; IT finishes the account by hand
                app.activity_schedule("mail.mail_activity_data_todo", user_id=(app.user_id or self.env.user).id,
                                      summary="Create %s's Microsoft account" % app.partner_name,
                                      note=Markup("<p>Odoo could not create it: %s</p><p>Make it in Microsoft, then click "
                                                  "<b>Create work account</b> again.</p>") % str(e))
        return True

    @api.model
    def create_work_account(self, applicant_ids):
        """Microsoft 365 account first, then the Odoo login with that work email."""
        for app in self.env["hr.applicant"].browse(applicant_ids):
            emp = app.employee_id
            if not emp:
                raise UserError("Confirm joined first.")
            if emp.user_id:
                raise UserError("%s already has an Odoo login." % emp.name)
            email, pwd = self.ms_create_user(app.partner_name, app.company_id.country_id.code or "IN")
            user = self.env["res.users"].sudo().with_context(no_reset_password=True).create({
                "name": emp.name, "login": email, "email": email,
                "partner_id": emp.work_contact_id.id,  # keeps the salary bank account on the same contact
                "create_employee_id": emp.id,  # link, do not make a second employee
                "company_id": emp.company_id.id, "company_ids": [(6, 0, emp.company_id.ids)]})
            emp.sudo().write({"work_email": email, "user_id": user.id})
            app.sudo().write({"x_work_email": email, "x_ms_temp_pwd": pwd})
            app.message_post(body=Markup("Microsoft account and Odoo login created: <b>%s</b>. "
                                         "Hand over the temporary password in person.") % email)
        return True

    def _create_employee(self, app, form):
        company = app.company_id
        emp = self.env["hr.employee"].sudo().create({"name": app.partner_name, "company_id": company.id})
        req = app.x_hiring_request_id
        manager = req.x_hiring_manager_id.employee_ids.filtered(lambda e: e.company_id == company)[:1] if req else False
        emp.write({
            "job_id": (req.x_job_id or app.job_id).id, "job_title": app.x_offer_designation or app.job_id.name,
            "department_id": (req.x_department_id or app.department_id).id, "parent_id": manager.id if manager else False,
            "private_email": form.x_email, "private_phone": form.x_phone, "birthday": form.x_dob, "sex": form.x_gender,
            "private_street": form.x_addr_current, "emergency_contact": "%s (%s)" % (form.x_emg_name, form.x_emg_relation),
            "emergency_phone": form.x_emg_phone, "l10n_in_pan": form.x_pan_number, "l10n_in_uan": form.x_uan,
            "x_studio_blood_group": form.x_blood_group, "contract_date_start": app.x_offer_doj})
        return emp

    def _add_bank_account(self, emp, form):
        Bank = self.env["res.bank"].sudo()
        bank = Bank.search([("bic", "=", form.x_bank_ifsc)], limit=1) or Bank.create(
            {"name": form.x_bank_name, "bic": form.x_bank_ifsc})  # bic holds the IFSC code
        acc = self.env["res.partner.bank"].sudo().create({
            "partner_id": emp.work_contact_id.id, "acc_number": form.x_bank_account,
            "acc_holder_name": form.x_bank_holder, "bank_id": bank.id})
        emp.write({"bank_account_ids": [(4, acc.id)], "primary_bank_account_id": acc.id})
        return acc

    def _tell_linda(self, emp, acc):
        """A link only, never the numbers (LinkedERP rule)."""
        login = self.env["ir.config_parameter"].sudo().get_param("hr_office.bank_approver_login", "linda@linkederp.com")
        linda = self.env["res.users"].sudo().search([("login", "=", login)], limit=1)
        if not linda:
            return
        link = "%s/odoo/action-base.action_res_partner_bank_account_form/%s" % (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url"), acc.id)
        acc.activity_schedule("mail.mail_activity_data_todo", user_id=linda.id,
                              summary="Add %s's bank account for salary" % emp.name,
                              note=Markup("<p>%s joined today. Please add this account as a beneficiary in the bank, "
                                          "then tick <b>Send Money</b> on it in Odoo.</p>") % emp.name)
        self.env["mail.mail"].sudo().create({
            "email_to": linda.email, "subject": "New joiner: please add %s's bank account" % emp.name,
            "body_html": Markup("<p>Hi %s,</p><p>%s (%s) joined today. Please add their salary account as a beneficiary "
                                "in the bank. The details are in Odoo (no numbers in this email):</p>"
                                "<p><a href='%s'>Open the bank account in Odoo</a></p><p>Thank you,<br/>HR Office</p>")
                         % (linda.name.split(" ")[0], emp.name, emp.company_id.name, link)}).send()

    def _announce(self, emp):
        channel = self.env["discuss.channel"].sudo().search([("name", "=", "general")], limit=1)
        if not channel:
            return
        mgr = Markup(" Reporting to <b>%s</b>.") % emp.parent_id.name if emp.parent_id else ""
        channel.message_post(body=Markup("<p>Please welcome <b>%s</b>, who joins %s today as <b>%s</b>.%s Say hello!</p>")
                             % (emp.name, emp.company_id.name, emp.job_title or "", mgr),
                             message_type="comment", subtype_xmlid="mail.mt_comment")

    def _send_pf_pack(self, app, form):
        if app.company_id.country_id.code != "IN":
            return
        files = [("PF Form 11.pdf", "form_11.pdf")] + ([] if form.x_uan else [("How to create your UAN.pdf", "uan_guide.pdf")])
        atts = self.env["ir.attachment"].sudo().create([{
            "name": name, "res_model": "hr.applicant", "res_id": app.id,
            "datas": base64.b64encode(file_open("linkederp_jd_helper/data/onboarding/" + path, "rb").read())}
            for name, path in files])
        uan = ("<p>You already have a UAN, so please just fill in Form 11.</p>" if form.x_uan else
               "<p>If you do not have a UAN yet, please create one with the attached guide and send it to HR.</p>")
        app.message_post(subject="Welcome! Your PF Form 11", partner_ids=app.partner_id.ids, attachment_ids=atts.ids,
                         message_type="comment", subtype_xmlid="mail.mt_comment",
                         body=Markup("<p>Dear %s,</p><p>Welcome to LinkedERP! Please fill in, sign and return the attached "
                                     "PF Form 11 to HR within your first week.</p>%s<p>HR team, LinkedERP India</p>")
                         % (app.partner_name.split(" ")[0], Markup(uan)))
        app.activity_schedule("mail.mail_activity_data_todo", date_deadline=fields.Date.context_today(self) + timedelta(days=7),
                              user_id=(app.user_id or self.env.user).id,
                              summary="Collect PF Form 11%s from %s" % ("" if form.x_uan else " and UAN", app.partner_name))
