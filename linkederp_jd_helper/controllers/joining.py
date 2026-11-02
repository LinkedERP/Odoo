# -*- coding: utf-8 -*-
"""Public joining form: /joining/<token>. The token is the only key; no Odoo login is needed."""
from odoo import http
from odoo.http import request

from ..models.onboarding import FIELDS, UPLOADS

UPPER = ("x_pan_number", "x_bank_ifsc")


class JoiningForm(http.Controller):

    def _form(self, token):
        form = request.env["x_joining_form"].sudo().search([("x_token", "=", token or "")], limit=1) if token and len(token) == 32 else None
        if not form:
            raise request.not_found()
        return form

    def _render(self, form, values=None, errors=None):
        return request.render("linkederp_jd_helper.joining_page", {
            "form": form, "app": form.x_applicant_id, "fields": FIELDS, "uploads": UPLOADS,
            "values": values or {}, "errors": errors or [], "done": form.x_state == "submitted"})

    @http.route("/joining/<string:token>", type="http", auth="public", methods=["GET"], sitemap=False)
    def show(self, token, **kw):
        form = self._form(token)
        values = {"x_email": form.x_email, "x_phone": form.x_phone, "x_pan_name": form.x_applicant_id.partner_name}
        return self._render(form, values)

    @http.route("/joining/<string:token>", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def submit(self, token, **post):
        form = self._form(token)
        if form.x_state == "submitted":
            return self._render(form)
        vals = {}
        for name, _label, _req, _kind in FIELDS:
            v = (post.get(name) or "").strip()
            vals[name] = v.upper().replace(" ", "") if name in UPPER else v
        files = {key: [f for f in request.httprequest.files.getlist(key) if f and f.filename] for key, *_ in UPLOADS}
        worked = {"yes": True, "no": False}.get(post.get("worked_before"))
        errors = request.env["linkederp.jd.helper"].sudo().save_joining_form(form, vals, files, worked)
        return self._render(form, dict(vals, worked_before=post.get("worked_before")), errors)
