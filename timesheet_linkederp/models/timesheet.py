from odoo import models, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo import api, fields, models


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _domain_project_id(self):
        domain = Domain([('allow_timesheets', '=', True), ('is_template', '=', False), ('reinvoiced_sale_order_id.locked', '=', False)])
        if not self.env.user.has_group('hr_timesheet.group_timesheet_manager'):
            domain &= Domain('privacy_visibility', 'in', ['employees', 'portal']) | Domain('message_partner_ids', 'in',                                                                     [self.env.user.partner_id.id])
        return domain

    project_id = fields.Many2one(
        'project.project', 'Project', domain=_domain_project_id, index=True,
        compute='_compute_project_id', store=True, readonly=False)

    @api.constrains('project_id')
    def _check_project_company_vs_current_company(self):
        """Prevent logging timesheet if project company != currently selected company."""
        current_company = self.env.company  # company chosen in top-right profile switcher
        for record in self:
            if record.project_id and record.project_id.company_id != current_company:
                self.project_id = False  # clear project selection
                raise ValidationError(
                    _("You cannot log a timesheet on a project that belongs to another company.\n"
                      "Your current company: %s\nProject company: %s") %
                    (current_company.display_name, record.project_id.company_id.display_name)
                )
                return {'warning': warning}

    @api.onchange('project_id')
    def _onchange_project_company_vs_current_company(self):
        """Show warning immediately in form view when project != current company."""
        current_company = self.env.company
        if self.project_id and self.project_id.company_id != current_company:
            self.project_id = False # clear project selection
            return {
                'warning': {
                    'title': _("Invalid Project"),
                    'message': _("This project belongs to another company. "
                                 "You cannot log a timesheet for it while working in %s.")
                               % current_company.display_name,
                }
            }
