from odoo import api, fields, models


class ShubhadaDivision(models.Model):
    """A plant/division. Galaxy scopes every document, report and permission by it."""
    _name = 'shubhada.division'
    _description = 'Division'
    _order = 'code'

    name = fields.Char(required=True)
    code = fields.Char(
        required=True, size=8,
        help="Short code shown next to the division on documents, e.g. NSK.")
    number_letter = fields.Char(
        required=True, size=1,
        help="Single character used in the document number, e.g. N for Nashik.")
    company_letters = fields.Char(
        required=True, size=2, default='SH',
        help="Two-letter company prefix in the document number: "
             "SH = Shubhada Polymers, ST = Shubhada Technologies.")
    warehouse_ids = fields.Many2many(
        'stock.warehouse', string='Plants',
        help="Plants that belong to this division.")
    company_id = fields.Many2one(
        'res.company',
        help="Leave empty to share the division across companies.")
    active = fields.Boolean(default=True)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} {rec.name}' if rec.code else rec.name


class ShubhadaPoSeries(models.Model):
    """A purchase series (segment). Each carries its own serial and its own buyers."""
    _name = 'shubhada.po.series'
    _description = 'Purchase Series'
    _order = 'code'

    name = fields.Char(required=True, help="e.g. PO - BOUGHTOUT MATERIAL")
    code = fields.Char(required=True, size=8, help="e.g. PC01")
    document_code = fields.Char(
        required=True, size=4, default='PO',
        help="Document code inside the number, e.g. PO.")
    next_serial = fields.Integer(
        default=1, required=True,
        help="Next running serial for this series. Galaxy keeps one counter per series.")
    serial_padding = fields.Integer(default=5, required=True)
    buyer_group_id = fields.Many2one(
        'res.groups', string='Buyer Group',
        help="Only members of this group may raise or see orders in this series. "
             "Leave empty to allow every buyer.")
    company_id = fields.Many2one(
        'res.company',
        help="Leave empty to share the series across companies.")
    active = fields.Boolean(default=True)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} — {rec.name}' if rec.code else rec.name

    def _take_next_serial(self):
        """Reserve and return the next serial for this series.

        ponytail: a plain read-then-write under Odoo's row lock. Fine at Shubhada's
        volume; move to an ir.sequence per series if two buyers ever post in the
        same millisecond.
        """
        self.ensure_one()
        serial = self.next_serial
        self.sudo().write({'next_serial': serial + 1})
        return serial


class ShubhadaPoDocRef(models.Model):
    """Source document a purchase order answers — normally a Purchase Requisition."""
    _name = 'shubhada.po.doc.ref'
    _description = 'Purchase Document Reference'

    order_id = fields.Many2one('purchase.order', required=True, ondelete='cascade')
    document_type = fields.Selection(
        [('PR', 'PR — Purchase Requisition'),
         ('IN', 'IN — Indent'),
         ('CO', 'CO — Contract'),
         ('OT', 'OT — Other')],
        default='PR', required=True)
    document_number = fields.Char(required=True)
    amendment_number = fields.Integer(default=0)
    department_code = fields.Char(string='Department', help="e.g. STORES")
    department_name = fields.Char(string='Department Name', help="e.g. STORES DEPARTMENT")
    quantity = fields.Float()


class ShubhadaPoSchedule(models.Model):
    """Delivery schedule under a purchase order line — Galaxy's per-line grid."""
    _name = 'shubhada.po.schedule'
    _description = 'Purchase Line Delivery Schedule'
    _order = 'required_date'

    line_id = fields.Many2one('purchase.order.line', required=True, ondelete='cascade')
    order_id = fields.Many2one(related='line_id.order_id', store=True)
    required_date = fields.Date(required=True, default=fields.Date.context_today)
    required_qty = fields.Float(required=True)
    state = fields.Selection(
        [('draft', 'Draft'),
         ('confirmed', 'Confirmed'),
         ('received', 'Received'),
         ('short_closed', 'Short Closed'),
         ('cancelled', 'Cancelled')],
        default='confirmed', required=True)
    received_qty = fields.Float()
    rejected_qty = fields.Float()
    short_closed_qty = fields.Float()
    cancelled_qty = fields.Float()
    supplier_conf_ref = fields.Char(string='Supplier Conf. Ref. No.')
    supplier_conf_date = fields.Date(string='Ref. Dt.')
