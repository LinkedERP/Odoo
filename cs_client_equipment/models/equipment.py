# -*- coding: utf-8 -*-

#################################################################################
# Author      : Cyder Solutions (<www.cyder.com.au>)
# Copyright(c): 2021-now
# All Rights Reserved.
#
# This module is copyright property of the author mentioned above.
# You can't redistribute/reshare/recreate it for any purpose.
#################################################################################

from odoo import api, fields, models, _
from . import base_geocoder

class EquipmentDetails(models.Model):
    _name = "equipment.details"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Equipment Details"

    name = fields.Char('Equipment Name', required=True, translate=True)
    category_id = fields.Many2one('equipment.category', string='Equipment Category',
                                  tracking=True, group_expand='_read_group_category_ids')
    client = fields.Many2one('res.partner', string='Client', tracking=True)
    manufacturer_id = fields.Many2one('equipment.manufacturer', string='Manufacturer')
    ref = fields.Char('Reference')
    asset_tag = fields.Char('Asset Tag')
    location = fields.Char('Equipment Location')
    address = fields.Char('Equipment Address')
    model = fields.Char('Model')
    serial_no = fields.Char('Serial Number', copy=False)
    image = fields.Image(string="Image")
    street = fields.Char('Street')
    street2 = fields.Char('Street2')
    zip = fields.Char('Zip')
    city = fields.Char('City')
    state = fields.Many2one("res.country.state", string='State')
    country = fields.Many2one('res.country', string='Country')
    site_contact = fields.Char(string="Site Contact")
    site_phone = fields.Char(string="Site Phone")
    note = fields.Html(string='Note')
    history = fields.Html('History')
    latitude = fields.Float('Latitude', digits=(10, 7))
    longitude = fields.Float('Longitude', digits=(10, 7))
    file_ids = fields.Many2many('ir.attachment', string="Documents", copy=False)
    jobs = fields.One2many('equipment.jobs', 'equipment', string='Jobs')
    # New field for product linkage
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        tracking=True,
        help="The product that this equipment represents"
    )

    @api.onchange('client')
    def onchange_client(self):
        for rec in self:
            if rec.client:
                rec.site_contact = rec.client.site_contact
                rec.site_phone = rec.client.site_phone

    @api.onchange('product_id')
    def onchange_product_id(self):
        """Update equipment details based on selected product"""
        for record in self:
            if record.product_id:
                # Set manufacturer if available on product
                if hasattr(record.product_id, 'manufacturer_id') and record.product_id.manufacturer_id:
                    record.manufacturer_id = record.product_id.manufacturer_id
                
                # Set model to product name if empty
                if not record.model:
                    record.model = record.product_id.name
                
                # Set reference to product code if empty
                if not record.ref and record.product_id.default_code:
                    record.ref = record.product_id.default_code
                
                # Set category if available and empty
                if hasattr(record.product_id, 'equipment_category_id') and record.product_id.equipment_category_id:
                    record.category_id = record.product_id.equipment_category_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('client'):
                partner = self.env['res.partner'].browse(vals['client'])
                vals['site_contact'] = partner.site_contact
                vals['site_phone'] = partner.site_phone
        return super().create(vals_list)

    # @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        if default is None:
            default = {}
        if not default.get('name'):
            default['name'] = _("%s (copy)", self.name)
        return super(EquipmentDetails, self).copy(default)

    _sql_constraints = [
        ('unique_equipment_serial_no', 'unique (serial_no)', 'Serial No must be unique.'),
        ('unique_equipment_asset_tag', 'unique (asset_tag)', 'Asset Tags must be unique.'),
    ]

class EquipmentCategory(models.Model):
    _name = "equipment.category"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "equipment.category"

    name = fields.Char('Category Name', required=True, translate=True)

class EquipmentManufacturer(models.Model):
    _name = "equipment.manufacturer"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "equipment.manufacturer"

    name = fields.Char('Manufacturer Name', required=True, translate=True)
