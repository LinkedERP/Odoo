from odoo import models, fields

class MandatoryField(models.Model):
    _name = "mandatory.field.rule"
    _description = "Mandatory Field Rule"
    _rec_name = "field_id"

    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        ondelete="cascade"
    )

    field_id = fields.Many2one(
        "ir.model.fields",
        string="Field",
        required=True,
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('ttype', 'not in', ('one2many', 'many2many'))]"
    )

    active = fields.Boolean(default=True)
