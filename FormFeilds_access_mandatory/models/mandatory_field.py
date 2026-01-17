from odoo import models, fields

class MandatoryField(models.Model):
    _name = mandatory.field.rule
    _description = Mandatory Field Rule

    name = fields.Char(required=True)
    model_id = fields.Many2one(
        ir.model,
        required=True,
        domain=[(model, =, res.partner)]
    )
    field_id = fields.Many2one(
        ir.model.fields,
        required=True,
        domain=[('model_id', '=', model_id), ('ttype', 'not in', ('one2many', 'many2many'))]
    )
    active = fields.Boolean(default=True)
