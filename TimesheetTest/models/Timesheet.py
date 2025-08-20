from odoo import models, api, _
from odoo.exceptions import UserError


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.constrains('project_id')
    def _check_project_company_vs_user_company(self):
        """Prevent logging timesheet if project company != user's company."""
        for record in self:
            if record.project_id and record.project_id.company_id != record.company_id:
                raise UserError(
                    _("You cannot log a timesheet on a project that belongs to another company.\n"
                      "Your company: %s\nProject company: %s") %
                    (record.company_id.display_name, record.project_id.company_id.display_name)
                )
