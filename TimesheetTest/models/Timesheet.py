from odoo import models, api, _
from odoo.exceptions import UserError


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.constrains('project_id')
    def _check_project_company_vs_user_company(self):
        """Prevent logging timesheet if project company != user's company."""
        user_company = self.env.user.company_id
        for record in self:
            if record.project_id and record.project_id.company_id != user_company:
                raise UserError(
                    _("You cannot log a timesheet on a project that belongs to another company.\n"
                      "Your company: %s\nProject company: %s") %
                    (user_company.display_name, record.project_id.company_id.display_name)
                )
                
    @api.onchange('project_id')
    def _onchange_project_company_vs_user_company(self):
        user_company = self.env.user.company_id
        if self.project_id and self.project_id.company_id != user_company:
            return {
                'warning': {
                    'title': _("Invalid Project"),
                    'message': _("This project belongs to another company. You cannot log time here."),
                }
            }            

