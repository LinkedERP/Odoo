from odoo import models, api, fields
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = "res.partner"

    require_phone = fields.Boolean(string="Require Phone")
    require_email = fields.Boolean(string="Require Email")
    require_vat = fields.Boolean(string="Require VAT")


    @api.constrains('require_phone', 'phone')
    def _check_required_phone(self):
        for rec in self:
            if rec.require_phone and not rec.phone:
                raise ValidationError("Phone is required as per configuration.")

    @api.constrains('require_email', 'email')
    def _check_required_email(self):
        for rec in self:
            if rec.require_email and not rec.email:
                raise ValidationError("Email is required as per configuration.")

    @api.constrains('require_vat', 'vat')
    def _check_required_vat(self):
        for rec in self:
            if rec.require_vat and not rec.vat:
                raise ValidationError("VAT is required as per configuration.")
