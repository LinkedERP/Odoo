from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ShubhadaPoAmendment(models.Model):
    """A commercial amendment to a posted purchase order.

    This is the thing Mahesh Joshi said Odoo does not have, and he was right:

        "If I have received partial material, two GRNs are made... and there is a
         commercial amendment, on the statutory front or on the rate front... only
         from a certain date that rate should be applicable to the receipts you have
         done. You can select from which GRN you can change that rate."

    So an amendment carries a new rate and an effective date, lists every receipt
    already made against the line, and lets a manager choose which of those receipts
    the new rate reaches back to. Applying it repricing the open balance of the order
    AND revalues only the ticked receipts.
    """
    _name = 'shubhada.po.amendment'
    _description = 'Purchase Order Amendment'
    _order = 'id desc'
    _inherit = ['mail.thread']

    name = fields.Char(readonly=True, copy=False, default='New')
    order_id = fields.Many2one(
        'purchase.order', required=True, ondelete='cascade', readonly=True)
    line_id = fields.Many2one(
        'purchase.order.line', string='Item', required=True,
        domain="[('order_id', '=', order_id)]")
    product_id = fields.Many2one(related='line_id.product_id', readonly=True)
    currency_id = fields.Many2one(related='order_id.currency_id', readonly=True)

    amendment_type = fields.Selection(
        [('rate', 'Rate revision'),
         ('statutory', 'Statutory / tax revision')],
        default='rate', required=True,
        help="Galaxy distinguishes a commercial rate change from a statutory one. "
             "Both reprice; only the reason and the audit wording differ.")
    old_rate = fields.Float(string='Existing Rate', readonly=True)
    new_rate = fields.Float(string='Revised Rate', required=True)
    effective_date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="Receipts on or after this date are the ones the revised rate reaches.")
    reason = fields.Text(
        help="Required before the amendment can be applied - checked in action_apply "
             "rather than at create, so the record can be opened and filled in.")

    receipt_ids = fields.One2many(
        'shubhada.po.amendment.receipt', 'amendment_id', string='Receipts (GRNs)')
    selected_count = fields.Integer(compute='_compute_totals')
    difference_total = fields.Monetary(
        compute='_compute_totals', currency_field='currency_id',
        help="What the ticked receipts are worth at the revised rate, minus what "
             "they were booked at.")

    state = fields.Selection(
        [('draft', 'Draft'), ('applied', 'Applied')],
        default='draft', readonly=True, copy=False, tracking=True)
    applied_uid = fields.Many2one('res.users', string='Applied by', readonly=True)
    applied_on = fields.Datetime(string='Applied on', readonly=True)

    @api.depends('receipt_ids.selected', 'receipt_ids.difference')
    def _compute_totals(self):
        for rec in self:
            picked = rec.receipt_ids.filtered('selected')
            rec.selected_count = len(picked)
            rec.difference_total = sum(picked.mapped('difference'))

    # ------------------------------------------------------------------ setup
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'shubhada.po.amendment') or 'AMD/NEW'
        records = super().create(vals_list)
        # only build the grid for records created without one (e.g. over RPC);
        # a form the user filled in already carries its ticked rows
        records.filtered(lambda r: not r.receipt_ids)._load_receipts()
        return records

    @api.onchange('line_id')
    def _onchange_line_id(self):
        """Keep the rates in step when the item changes.

        The grid itself is built server-side in create(), because rows invented by
        an onchange lose move_id when Odoo saves them.
        """
        if not self.line_id:
            return
        self.old_rate = self.line_id.price_unit
        if not self.new_rate:
            self.new_rate = self.line_id.price_unit
        self._onchange_reprice()

    @api.onchange('new_rate', 'effective_date')
    def _onchange_reprice(self):
        """Re-tick by date and re-cost, so the grid answers as you type."""
        for line in self.receipt_ids:
            # move.date is a Datetime, effective_date is a Date - compare like for like
            received_on = line.date.date() if line.date else False
            line.selected = bool(
                self.effective_date and received_on and received_on >= self.effective_date)
            line._recost(self.new_rate)

    def _load_receipts(self):
        """Pull the done receipts already made against this line."""
        Receipt = self.env['shubhada.po.amendment.receipt']
        for rec in self:
            rec.receipt_ids.unlink()
            moves = rec.line_id.move_ids.filtered(
                lambda m: m.state == 'done' and m.picking_id)
            for move in moves:
                Receipt.create({
                    'amendment_id': rec.id,
                    'move_id': move.id,
                    'quantity': move.quantity,
                    'old_rate': move.price_unit or rec.line_id.price_unit,
                })
            rec.old_rate = rec.line_id.price_unit
            rec._onchange_reprice()

    def action_reload_receipts(self):
        self._load_receipts()
        return True

    # ------------------------------------------------------------------ apply
    def action_apply(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('This amendment has already been applied.'))
            if not rec.new_rate:
                raise UserError(_('Set the revised rate first.'))
            if not (rec.reason or '').strip():
                raise UserError(_(
                    'Give a reason. An amendment without one is just an edit.'))

            # 1. the open balance of the order carries the new rate from here on
            rec.line_id.price_unit = rec.new_rate

            # 2. only the ticked receipts are reached back into
            for line in rec.receipt_ids.filtered('selected'):
                line._apply_to_move(rec.new_rate)

            # 3. the order itself is now an amended document and goes back
            #    through the approval chain - a posted order is never quietly edited
            rec.order_id.action_galaxy_amend()

            rec.write({
                'state': 'applied',
                'applied_uid': self.env.uid,
                'applied_on': fields.Datetime.now(),
            })
            rec.order_id.message_post(body=_(
                '<b>%(name)s applied.</b> %(product)s repriced %(old).2f → %(new).2f '
                'with effect from %(date)s. %(count)d receipt(s) revalued, '
                'difference %(diff).2f.',
                name=rec.name, product=rec.product_id.display_name,
                old=rec.old_rate, new=rec.new_rate,
                date=rec.effective_date, count=rec.selected_count,
                diff=rec.difference_total))
        return True


class ShubhadaPoAmendmentReceipt(models.Model):
    """One GRN under an amendment — the row Mahesh ticks or leaves alone."""
    _name = 'shubhada.po.amendment.receipt'
    _description = 'Amendment Receipt Line'
    _order = 'date'

    amendment_id = fields.Many2one(
        'shubhada.po.amendment', required=True, ondelete='cascade')
    move_id = fields.Many2one('stock.move', required=True, ondelete='cascade')
    picking_id = fields.Many2one(related='move_id.picking_id', string='GRN', readonly=True)
    date = fields.Datetime(related='move_id.date', string='Received on', readonly=True)
    currency_id = fields.Many2one(related='amendment_id.currency_id', readonly=True)

    quantity = fields.Float(readonly=True)
    old_rate = fields.Float(string='Booked at', readonly=True)
    new_rate = fields.Float(string='Revised to', readonly=True)
    old_value = fields.Monetary(
        compute='_compute_values', currency_field='currency_id', string='Booked value')
    new_value = fields.Monetary(
        compute='_compute_values', currency_field='currency_id', string='Revised value')
    difference = fields.Monetary(
        compute='_compute_values', currency_field='currency_id', store=True)
    selected = fields.Boolean(
        string='Apply', help="Tick the receipts this revised rate reaches back to.")

    @api.depends('quantity', 'old_rate', 'new_rate')
    def _compute_values(self):
        for line in self:
            line.old_value = line.quantity * line.old_rate
            line.new_value = line.quantity * line.new_rate
            line.difference = line.new_value - line.old_value

    def _recost(self, new_rate):
        for line in self:
            line.new_rate = new_rate

    def _apply_to_move(self, new_rate):
        """Reprice the receipt itself.

        ponytail: this rewrites the move's unit price and value. It deliberately does
        NOT post the correcting journal entry, because this database has
        property_valuation = real_time with NO stock valuation account configured on
        the category - posting into that would create a half-formed entry on a shared
        demo instance. The difference is computed and recorded here; wiring the entry
        is a configuration step (valuation + price-difference accounts) in the real
        implementation, not a code change.
        """
        for line in self:
            vals = {'price_unit': new_rate}
            if 'value' in line.move_id._fields:
                vals['value'] = line.quantity * new_rate
            line.move_id.sudo().write(vals)
            # old_rate deliberately NOT touched. It is the rate the receipt was
            # booked at, and it has to survive so the applied amendment keeps
            # showing 862 -> 892 and the difference it caused. Overwriting it
            # recomputed every difference to zero and emptied the audit trail.
