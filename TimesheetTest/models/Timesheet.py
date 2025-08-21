from odoo import models, api, _
from odoo.exceptions import ValidationError


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.constrains('project_id')
    def _check_project_company_vs_current_company(self):
        """Prevent logging timesheet if project company != currently selected company."""
        current_company = self.env.company  # company chosen in top-right profile switcher
        for record in self:
            if record.project_id and record.project_id.company_id != current_company:
                raise ValidationError(
                    _("You cannot log a timesheet on a project that belongs to another company.\n"
                      "Your current company: %s\nProject company: %s") %
                    (current_company.display_name, record.project_id.company_id.display_name)
                )
                self.project_id = False  # clear project selection
                return {'warning': warning}

    @api.onchange('project_id')
    def _onchange_project_company_vs_current_company(self):
        """Show warning immediately in form view when project != current company."""
        current_company = self.env.company
        if self.project_id and self.project_id.company_id != current_company:
            return {
                'warning': {
                    'title': _("Invalid Project"),
                    'message': _("This project belongs to another company. "
                                 "You cannot log a timesheet for it while working in %s.")
                               % current_company.display_name,
                }
            }
