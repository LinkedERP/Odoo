from odoo import models, fields

class ResPartner(models.Model):
    _inherit = "res.partner"

    require_phone = fields.Boolean(string="Require Phone")
    require_email = fields.Boolean(string="Require Email")
    require_vat = fields.Boolean(string="Require VAT")
