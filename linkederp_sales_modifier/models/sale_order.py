from odoo import models, api, _
from odoo.exceptions import UserError
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_lock(self):
        """Override lock to allow locking regardless of invoice_status."""
        self.locked = True
    def action_unlock(self):
        """Override unlock - always allow unlocking."""
        self.locked = False
