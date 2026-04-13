from odoo import models
from odoo.fields import Domain
from odoo.tools.misc import unquote
class AccountAnalyticLine(models.Model):
    """Extend timesheet lines to exclude locked Sale Orders from the SO line domain."""
    _inherit = 'account.analytic.line'
    def _domain_so_line(self):
        """Extend parent domain to exclude locked sale orders from the SO line selector."""
        parent_domain = super()._domain_so_line()
        not_locked_domain = Domain([('order_id.locked', '=', False)])
        return str(Domain.AND([Domain(parent_domain), not_locked_domain]))
