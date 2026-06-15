# -*- coding: utf-8 -*-
from odoo import models, fields
class Al3ConfigArea(models.Model):
    _name = 'al3.config.area'
    _description = 'AL3 Configuration Export Area'
    _order = 'sequence, name'

    name = fields.Char(string='Area Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(default=10)
    description = fields.Char(string='Description')
    tab_color = fields.Char(string='Tab Color (hex)', default='1F3864')
    active = fields.Boolean(default=True)
