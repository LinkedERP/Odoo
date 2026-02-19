from odoo import models, api, fields
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = "res.partner"

    require_phone = fields.Boolean(string="Require Phone")
    require_email = fields.Boolean(string="Require Email")
    require_vat = fields.Boolean(string="Require VAT")

    @api.constrains("email", "phone")
    def _check_duplicate_contacts(self):


        if self.env.context.get('from_crm_lead') or self.env.context.get('default_type') == 'opportunity':
            return
        for partner in self:
            domain = [("id", "!=", partner.id)]

            if partner.email:
                domain_email = domain + [("email", "=", partner.email)]
                if self.search_count(domain_email):
                    raise ValidationError(
                        "A contact with the same Email already exists.")

            if partner.phone:
                domain_phone = domain + [("phone", "=", partner.phone)]
                if self.search_count(domain_phone):
                    raise ValidationError("A contact with the same Phone number already exists.")

    @api.constrains('name')
    def _check_name_not_all_caps(self):
        for partner in self:
            if partner.name and partner.name.isupper():
                raise ValidationError("Contact name should not be in ALL CAPITAL letters.")

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
