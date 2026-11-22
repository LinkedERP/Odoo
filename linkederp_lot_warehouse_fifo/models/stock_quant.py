from odoo import api, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.depends('company_id', 'location_id', 'owner_id', 'product_id', 'quantity')
    def _compute_value(self):
        super()._compute_value()
        cache = {}
        for quant in self:
            product = quant.product_id
            wh = quant.location_id.warehouse_id
            if not quant.lot_id or not wh or not product._lwf_on() or not quant.location_id._should_be_valued():
                continue
            key = (quant.lot_id.id, wh.id)
            if key not in cache:
                layers = product.with_company(quant.company_id)._lwf_layers(quant.lot_id, wh)
                qty = sum(q for q, _u in layers)
                cache[key] = (sum(q * u for q, u in layers) / qty) if qty else quant.lot_id.standard_price
            quant.value = quant.quantity * cache[key]
