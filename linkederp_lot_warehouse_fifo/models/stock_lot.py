from odoo import api, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    # same triggers as stock_account's method (an override without them would lose them)
    @api.depends('product_id.lot_valuated', 'product_id.product_tmpl_id.lot_valuated', 'product_id.stock_move_ids.value', 'standard_price')
    @api.depends_context('to_date', 'company', 'warehouse_id', 'allowed_company_ids')
    def _compute_value(self):
        super()._compute_value()
        for lot in self:
            product = lot.product_id
            if not product or not product._lwf_on():
                continue
            wh_id = self.env.context.get('warehouse_id')
            if wh_id:
                warehouses = self.env['stock.warehouse'].browse(wh_id)
            else:
                quants = lot.quant_ids.filtered(lambda q: q.quantity > 0 and q.location_id._should_be_valued())
                warehouses = quants.location_id.warehouse_id
            total = sum(product._lwf_value(lot, wh) for wh in warehouses)
            qty = lot.product_qty
            lot.total_value = total
            lot.avg_cost = total / qty if qty else 0
