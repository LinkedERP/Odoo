from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _financial_year_suffix(date):
    """Indian FY suffix used in the document number: Aug-2026 -> '27' (FY 2026-27)."""
    year = date.year + 1 if date.month >= 4 else date.year
    return f'{year % 100:02d}'


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # ------------------------------------------------------------------ header
    x_galaxy_number = fields.Char(
        string='Number', copy=False, readonly=True, index=True,
        help="Galaxy-format document number. Assigned when the order is posted, "
             "not when it is saved.")
    x_series_id = fields.Many2one(
        'shubhada.po.series', string='Series', copy=False,
        help="Purchase segment. Drives the document number, the running serial "
             "and which buyers may see this order.")
    x_division_id = fields.Many2one('shubhada.division', string='By Location')
    x_for_division_id = fields.Many2one('shubhada.division', string='For Location')
    x_wef_date = fields.Date(string='With Effect From')
    x_validity_date = fields.Date(string='Validity Date')
    x_project_code = fields.Char(string='Project Code')

    x_amendment_no = fields.Integer(string='Amendment No.', default=0, copy=False, readonly=True)
    x_amendment_date = fields.Date(string='Amendment Date', copy=False, readonly=True)

    x_our_reference = fields.Char(string='Our Reference')
    x_party_quotation_no = fields.Char(string="Party's Quotation No.")
    x_party_quotation_date = fields.Date(string='Date')
    x_supplier_conf_remark = fields.Text(string='Supplier Confirmation Remark')
    x_confirmation_date = fields.Date(string='Confirmation Date')

    x_payment_mode = fields.Selection(
        [('credit', 'Credit'), ('advance', 'Advance'), ('cash', 'Cash'),
         ('lc', 'Letter of Credit')],
        string='Payment mode', default='credit')
    x_entry_tax_applicable = fields.Boolean(string='Entry Tax / Octroi Applicable?')
    x_advance_amount = fields.Monetary(string='Advance', currency_field='currency_id')
    x_period_code = fields.Char(
        string='Period code', compute='_compute_x_period_code', store=True,
        help="Accounting period the order falls in, e.g. 202608.")

    x_doc_ref_ids = fields.One2many(
        'shubhada.po.doc.ref', 'order_id', string='Document Reference')

    # ---------------------------------------------------------- maker-checker
    x_approval_state = fields.Selection(
        [('draft', 'Draft'),
         ('submitted', 'Submitted'),
         ('hod_approved', 'HOD Approved'),
         ('posted', 'Posted')],
        string='Approval', default='draft', copy=False, tracking=True)
    x_galaxy_status = fields.Selection(
        [('open', 'Open'),
         ('amended', 'Amended'),
         ('short_closed', 'Short Closed'),
         ('cancel', 'Cancel')],
        string='Status', copy=False)

    x_created_uid = fields.Many2one('res.users', string='Created by', readonly=True, copy=False)
    x_created_on = fields.Datetime(string='Created on', readonly=True, copy=False)
    x_modified_uid = fields.Many2one('res.users', string='Modified by', readonly=True, copy=False)
    x_modified_on = fields.Datetime(string='Modified on', readonly=True, copy=False)
    x_hod_uid = fields.Many2one('res.users', string='HOD approved by', readonly=True, copy=False)
    x_hod_on = fields.Datetime(string='HOD approved on', readonly=True, copy=False)
    x_posted_uid = fields.Many2one('res.users', string='Posted by', readonly=True, copy=False)
    x_posted_on = fields.Datetime(string='Posted on', readonly=True, copy=False)

    x_basic_amount = fields.Monetary(
        string='Basic Amount', compute='_compute_x_basic_amount',
        currency_field='currency_id')

    # ------------------------------------------------------------- computes
    @api.depends('date_order')
    def _compute_x_period_code(self):
        for order in self:
            order.x_period_code = order.date_order.strftime('%Y%m') if order.date_order else False

    @api.depends('order_line.price_subtotal')
    def _compute_x_basic_amount(self):
        for order in self:
            order.x_basic_amount = sum(order.order_line.mapped('price_subtotal'))

    # -------------------------------------------------------------- numbering
    def _galaxy_build_number(self):
        """SHN27PO04203 = company letters + division letter + FY + doc code + serial."""
        self.ensure_one()
        series = self.x_series_id
        division = self.x_division_id or self.x_for_division_id
        if not series or not division:
            raise UserError(_(
                'Set both a Series and a Location before posting — the document '
                'number is built from them.'))
        serial = series._take_next_serial()
        return '{co}{div}{fy}{doc}{serial:0{pad}d}'.format(
            co=division.company_letters,
            div=division.number_letter,
            fy=_financial_year_suffix(self.date_order or fields.Datetime.now()),
            doc=series.document_code,
            serial=serial,
            pad=series.serial_padding,
        )

    # ------------------------------------------------------------- workflow
    def action_galaxy_submit(self):
        for order in self:
            if order.x_approval_state != 'draft':
                raise UserError(_('Only a draft order can be submitted.'))
            if not order.order_line:
                raise UserError(_('Add at least one item before submitting.'))
            order.write({
                'x_approval_state': 'submitted',
                'x_modified_uid': self.env.user.id,
                'x_modified_on': fields.Datetime.now(),
            })
        return True

    def action_galaxy_approve_hod(self):
        for order in self:
            if order.x_approval_state != 'submitted':
                raise UserError(_('Only a submitted order can be approved by the HOD.'))
            if order.x_created_uid and order.x_created_uid == self.env.user:
                raise UserError(_(
                    'You raised this order. It has to be approved by someone else.'))
            order.write({
                'x_approval_state': 'hod_approved',
                'x_hod_uid': self.env.user.id,
                'x_hod_on': fields.Datetime.now(),
            })
        return True

    def action_galaxy_post(self):
        """Final approval. This is where the document number is born."""
        for order in self:
            if order.x_approval_state != 'hod_approved':
                raise UserError(_('The HOD has to approve before the order can be posted.'))
            vals = {
                'x_approval_state': 'posted',
                'x_galaxy_status': 'open',
                'x_posted_uid': self.env.user.id,
                'x_posted_on': fields.Datetime.now(),
            }
            if not order.x_galaxy_number:
                vals['x_galaxy_number'] = order._galaxy_build_number()
            order.write(vals)
            if order.state in ('draft', 'sent'):
                order.button_confirm()
        return True

    def action_galaxy_amend(self):
        for order in self:
            if order.x_approval_state != 'posted':
                raise UserError(_('Only a posted order can be amended.'))
            order.write({
                'x_approval_state': 'submitted',
                'x_galaxy_status': 'amended',
                'x_amendment_no': order.x_amendment_no + 1,
                'x_amendment_date': fields.Date.context_today(order),
                'x_modified_uid': self.env.user.id,
                'x_modified_on': fields.Datetime.now(),
            })
        return True

    def action_open_rate_amendment(self):
        """Open a fresh amendment for this order, first line pre-picked."""
        self.ensure_one()
        if self.x_approval_state != 'posted':
            raise UserError(_('Only a posted order can be amended.'))
        if not self.order_line:
            raise UserError(_('This order has no items to reprice.'))
        # Create the amendment server-side and open it, rather than opening a blank
        # form. An unsaved form builds its receipt rows in an onchange, and Odoo
        # then sends only the changed fields for those rows on save - which drops
        # move_id and fails with "Missing required value for the field 'Move'".
        # Creating first means the rows are real records from the outset.
        Amendment = self.env['shubhada.po.amendment']
        line = self.order_line[0]
        existing = Amendment.search([
            ('order_id', '=', self.id), ('state', '=', 'draft'),
        ], limit=1)
        amendment = existing or Amendment.create({
            'order_id': self.id,
            'line_id': line.id,
            'new_rate': line.price_unit,
            'old_rate': line.price_unit,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Amend Rate'),
            'res_model': 'shubhada.po.amendment',
            'res_id': amendment.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_galaxy_short_close(self):
        self.write({'x_galaxy_status': 'short_closed'})
        return True

    def action_galaxy_cancel(self):
        self.write({'x_galaxy_status': 'cancel'})
        return True

    # ------------------------------------------------------------- overrides
    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            vals.setdefault('x_created_uid', self.env.uid)
            vals.setdefault('x_created_on', now)
        return super().create(vals_list)

    def write(self, vals):
        # Do not re-stamp when the write IS the stamp, or the audit trail lies.
        stamp_fields = {
            'x_modified_uid', 'x_modified_on', 'x_approval_state', 'x_galaxy_status',
            'x_hod_uid', 'x_hod_on', 'x_posted_uid', 'x_posted_on', 'x_galaxy_number',
            'x_amendment_no', 'x_amendment_date',
        }
        if not stamp_fields & set(vals):
            vals = dict(vals, x_modified_uid=self.env.uid, x_modified_on=fields.Datetime.now())
        return super().write(vals)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    x_sc_bom = fields.Boolean(
        string='S/C BOM',
        help="Tick when this line is issued against a subcontracting bill of material.")
    x_incoming_operation = fields.Char(string='Incoming Operation')
    x_outgoing_operation = fields.Char(string='Outgoing Operation')
    x_asset_code = fields.Char(string='Asset Code')
    x_rate_per_qty = fields.Float(string='Rate/Qty', default=1.0)

    x_length = fields.Float(string='Length')
    x_width = fields.Float(string='Width')
    x_thickness = fields.Float(string='Thickness')
    x_od = fields.Float(string='OD')
    x_id = fields.Float(string='ID')
    x_cs = fields.Float(string='CS')

    x_last_purchase_rate = fields.Float(
        string='Last Rate', compute='_compute_x_last_purchase_rate',
        help="Rate on the most recent confirmed order for this product from this vendor.")
    x_schedule_ids = fields.One2many(
        'shubhada.po.schedule', 'line_id', string='Delivery Schedule')
    x_scheduled_qty = fields.Float(
        string='Total Sch. Qty', compute='_compute_x_scheduled_qty')

    @api.depends('product_id', 'order_id.partner_id')
    def _compute_x_last_purchase_rate(self):
        for line in self:
            rate = 0.0
            if line.product_id and line.order_id.partner_id:
                previous = self.search([
                    ('product_id', '=', line.product_id.id),
                    ('order_id.partner_id', '=', line.order_id.partner_id.id),
                    ('order_id.state', 'in', ('purchase', 'done')),
                    ('id', '!=', line._origin.id or 0),
                ], order='id desc', limit=1)
                rate = previous.price_unit
            line.x_last_purchase_rate = rate

    @api.depends('x_schedule_ids.required_qty')
    def _compute_x_scheduled_qty(self):
        for line in self:
            line.x_scheduled_qty = sum(line.x_schedule_ids.mapped('required_qty'))
