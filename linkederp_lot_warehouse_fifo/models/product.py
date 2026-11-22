from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    lwf_per_warehouse = fields.Boolean(
        'Batch cost per warehouse',
        help="FIFO by batch is kept separately in each warehouse. Needs FIFO costing and "
             "'Valuation by Lot/Serial' on the product.")


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _lwf_on(self):
        self.ensure_one()
        return bool(self.lot_valuated and self.cost_method == 'fifo' and self.categ_id.lwf_per_warehouse)

    def _lwf_layers(self, lot, warehouse):
        """Cost layers of `lot` inside `warehouse`, oldest first, as [qty, unit_cost].

        Built like Odoo's own FIFO stack (newest incoming first, until the on-hand quantity of
        the batch in that warehouse is covered), but only from what came INTO this warehouse:
        receipts (valued by Odoo) and transfers from another warehouse (valued by this module).
        """
        self.ensure_one()
        size = lot.with_context(warehouse_id=warehouse.id).product_qty
        if self.uom_id.compare(size, 0) <= 0:
            return []
        mls = self.env['stock.move.line'].search([
            ('product_id', '=', self.id),
            ('lot_id', '=', lot.id),
            ('state', '=', 'done'),
            ('picked', '=', True),
            ('location_dest_id.warehouse_id', '=', warehouse.id),
            ('company_id', '=', self.env.company.id),
        ], order='date desc, id desc')
        layers = []
        for ml in mls:
            move = ml.move_id
            if not ml.location_dest_id._should_be_valued():
                continue
            if move.is_in:
                valued_qty = move._get_valued_qty()
                unit = move.value / valued_qty if valued_qty else lot.standard_price
            elif ml.lwf_from_warehouse_id and ml.lwf_from_warehouse_id != warehouse:
                unit = ml.lwf_unit_cost
            else:
                continue  # moves inside the same warehouse do not change its stock
            take = min(ml.quantity_product_uom, size)
            layers.append([take, unit])
            size -= take
            if self.uom_id.compare(size, 0) <= 0:
                break
        if self.uom_id.compare(size, 0) > 0:
            layers.append([size, lot.standard_price])  # no history found: fall back to the batch cost
        layers.reverse()
        return layers

    def _lwf_consume(self, lot, warehouse, qty, already=0.0):
        """Value of taking `qty` of `lot` out of `warehouse`, oldest layer first.

        `already` is the quantity of the same batch and warehouse taken earlier in the same
        validation (stock is not reduced yet at that point).
        """
        value = 0.0
        last_unit = lot.standard_price
        for layer_qty, unit in self._lwf_layers(lot, warehouse):
            last_unit = unit
            if already > 0:
                skip = min(already, layer_qty)
                already -= skip
                layer_qty -= skip
            if layer_qty <= 0:
                continue
            take = min(layer_qty, qty)
            value += take * unit
            qty -= take
            if qty <= 0:
                break
        if qty > 0:
            value += qty * last_unit  # more than on hand: extend with the last known cost
        return value

    def _lwf_value(self, lot, warehouse):
        return sum(q * u for q, u in self._lwf_layers(lot, warehouse))
