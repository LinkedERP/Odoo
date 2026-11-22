from collections import defaultdict

from odoo import fields, models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    lwf_from_warehouse_id = fields.Many2one(
        'stock.warehouse', 'Transferred from warehouse', readonly=True, copy=False)
    lwf_unit_cost = fields.Float(
        'Transfer unit cost', readonly=True, copy=False, digits='Product Price')


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _lwf_is_out(self):
        return self.is_out if self.state == 'done' else bool(self._is_out())

    def _action_done(self, cancel_backorder=False):
        # Value transfers between warehouses BEFORE the stock moves: the source stack is read
        # as it is now.
        processed = defaultdict(float)
        for move in self:
            if not move.product_id._lwf_on() or move._is_in() or move._is_out():
                continue
            for ml in move.move_line_ids:
                if not ml.picked or not ml.lot_id:
                    continue
                src = ml.location_id.warehouse_id
                dst = ml.location_dest_id.warehouse_id
                if not src or not dst or src == dst:
                    continue
                if not (ml.location_id._should_be_valued() and ml.location_dest_id._should_be_valued()):
                    continue
                key = (ml.lot_id.id, src.id)
                qty = ml.quantity_product_uom
                value = move.product_id._lwf_consume(ml.lot_id, src, qty, processed[key])
                processed[key] += qty
                ml.write({'lwf_from_warehouse_id': src.id, 'lwf_unit_cost': value / qty if qty else 0.0})
        return super()._action_done(cancel_backorder=cancel_backorder)

    def _set_value(self, correction_quantity=None):
        if correction_quantity:
            return super()._set_value(correction_quantity=correction_quantity)
        lwf_out = self.filtered(lambda m: m.product_id._lwf_on() and m._lwf_is_out())
        res = super(StockMove, self - lwf_out)._set_value()
        processed = defaultdict(float)
        lots = self.env['stock.lot']
        for move in lwf_out.sorted(key=lambda m: (m.date, m.id)):
            move = move.with_company(move.company_id)
            value = 0.0
            for ml in move._get_out_move_lines():
                qty = ml.quantity_product_uom
                wh = ml.location_id.warehouse_id
                if ml.lot_id and wh:
                    key = (ml.lot_id.id, wh.id)
                    value += move.product_id._lwf_consume(ml.lot_id, wh, qty, processed[key])
                    processed[key] += qty
                    lots |= ml.lot_id
                else:
                    unit = ml.lot_id.standard_price if ml.lot_id else move.product_id.standard_price
                    value += unit * qty
            move.value = value
        if lots:
            lots._update_standard_price()
        return res
