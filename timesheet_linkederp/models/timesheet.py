# models/account_analytic_line.py
from odoo import models, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo import api, fields, models
from odoo.tools.misc import unquote


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _domain_project_id(self):
        domain = Domain([
            ('allow_timesheets', '=', True),
            ('is_template', '=', False),
            ('x_is_reinvoice_completed', '=', False),  # ← pakai field baru, bukan reinvoiced_sale_order_id
        ])
        if not self.env.user.has_group('hr_timesheet.group_timesheet_manager'):
            domain &= (
                Domain('privacy_visibility', 'in', ['employees', 'portal'])
                | Domain('message_partner_ids', 'in', [self.env.user.partner_id.id])
            )
        return domain

    def _domain_so_line(self):
        sale_orders = self.env['sale.order'].search([
            ('x_studio_completed', '=', False)
        ]).ids
        domain = [
            ('order_partner_id.commercial_partner_id', '=', unquote('commercial_partner_id')),
            ('order_id', 'in', sale_orders),
        ]
        return str(Domain.AND([
            self.env['sale.order.line']._sellable_lines_domain(),
            self.env['sale.order.line']._domain_sale_line_service(),
            domain,
        ]))

    @api.depends('helpdesk_ticket_id.sale_line_id')
    def _compute_so_line(self):
        non_billed_helpdesk_timesheets = self.filtered(
            lambda t: not t.is_so_line_edited
                      and t.helpdesk_ticket_id
                      and t._is_not_billed()
                      and not t.validated
        )

        for timesheet in non_billed_helpdesk_timesheets:
            so_line = timesheet.helpdesk_ticket_id.sale_line_id

            if (
                timesheet.project_id.allow_billable
                and so_line
                and not so_line.order_id.x_studio_completed
            ):
                timesheet.so_line = so_line
            else:
                timesheet.so_line = False

        super(AccountAnalyticLine, self - non_billed_helpdesk_timesheets)._compute_so_line()

    project_id = fields.Many2one(
        'project.project', 'Project', domain=_domain_project_id, index=True,
        compute='_compute_project_id', store=True, readonly=False)

    so_line = fields.Many2one(
        compute="_compute_so_line", store=True, readonly=False, default=False,
        domain=_domain_so_line, falsy_value_label="Non-billable",
        help="Sales order item to which the time spent will be added in order to be invoiced to your customer. "
             "Remove the sales order item for the timesheet entry to be non-billable.")

    @api.constrains('project_id')
    def _check_project_company_vs_current_company(self):
        """Prevent logging timesheet if project company != currently selected company."""
        current_company = self.env.company
        for record in self:
            if record.project_id and record.project_id.company_id != current_company:
                self.project_id = False
                raise ValidationError(
                    _("You cannot log a timesheet on a project that belongs to another company.\n"
                      "Your current company: %s\nProject company: %s") %
                    (current_company.display_name, record.project_id.company_id.display_name)
                )

    @api.onchange('project_id')
    def _onchange_project_company_vs_current_company(self):
        """Show warning immediately in form view when project != current company."""
        current_company = self.env.company
        if self.project_id and self.project_id.company_id != current_company:
            self.project_id = False
            return {
                'warning': {
                    'title': _("Invalid Project"),
                    'message': _("This project belongs to another company. "
                                 "You cannot log a timesheet for it while working in %s.")
                               % current_company.display_name,
                }
            }