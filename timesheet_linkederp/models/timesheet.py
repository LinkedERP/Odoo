from odoo import models, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo import api, fields, models
from odoo.tools.misc import unquote



class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _domain_project_id(self):
        domain = Domain([('allow_timesheets', '=', True), ('is_template', '=', False), ('reinvoiced_sale_order_id.locked', '=', False)])
        if not self.env.user.has_group('hr_timesheet.group_timesheet_manager'):
            domain &= Domain('privacy_visibility', 'in', ['employees', 'portal']) | Domain('message_partner_ids', 'in',                                                                     [self.env.user.partner_id.id])
        return domain

    # def _domain_so_line(self):
    #     """Extend parent domain to exclude locked sale orders from the SO line selector."""
    #     parent_domain = super()._domain_so_line()
    #     not_locked_domain = Domain([('order_id.locked', '=', False)])
    #     return str(Domain.AND([Domain(parent_domain), not_locked_domain]))
    #
    def _domain_so_line(self):
        domain = Domain.AND([
            self.env['sale.order.line']._sellable_lines_domain(),
            self.env['sale.order.line']._domain_sale_line_service(),
            [
                ('order_partner_id.commercial_partner_id', '=', unquote('commercial_partner_id')),
                ('order_id.locked', '=', False),
            ],
        ])
        return str(domain)

    project_id = fields.Many2one(
        'project.project', 'Project', domain=_domain_project_id, index=True,
        compute='_compute_project_id', store=True, readonly=False)

    so_line = fields.Many2one(compute="_compute_so_line", store=True, readonly=False,
                              domain=_domain_so_line, falsy_value_label="Non-billable",
                              help="Sales order item to which the time spent will be added in order to be invoiced to your customer. Remove the sales order item for the timesheet entry to be non-billable.")

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
