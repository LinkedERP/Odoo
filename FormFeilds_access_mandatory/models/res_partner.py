from odoo import models, api
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.constrains()
    def _check_mandatory_fields(self):
        rules = self.env["mandatory.field.rule"].search([
            ("model_id.model", "=", "res.partner"),
            ("active", "=", True),
        ])

        for rec in self:
            for rule in rules:
                field_name = rule.field_id.name
                value = rec[field_name]

                if not value:
                    raise ValidationError(
                        f"The field '{rule.field_id.field_description}' is mandatory."
                    )
