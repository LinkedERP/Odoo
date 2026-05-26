from odoo import models, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo import api, fields, models
from odoo.tools.misc import unquote



class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _domain_project_id(self):
        unlocked_project_ids = self.env['project.project'].sudo().search([
            ('reinvoiced_sale_order_id.locked', '=', False)
        ]).ids

        domain = Domain([
            ('allow_timesheets', '=', True),
            ('is_template', '=', False),
            ('id', 'in', unlocked_project_ids),
        ])

        if not self.env.user.has_group('hr_timesheet.group_timesheet_manager'):
            domain &= (
                    Domain('privacy_visibility', 'in', ['employees', 'portal'])
                    | Domain('message_partner_ids', 'in', [self.env.user.partner_id.id])
            )

        return domain

    def _domain_so_line(self):
        sale_orders = self.env['sale.order'].search([
            ('locked', '=', False)
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
                    and not so_line.order_id.locked  # 🔥 filter di sini
            ):
                timesheet.so_line = so_line
            else:
                timesheet.so_line = False  # penting supaya ga nyangkut value lama

        super(AccountAnalyticLine, self - non_billed_helpdesk_timesheets)._compute_so_line()

    project_id = fields.Many2one(
        'project.project', 'Project', domain=_domain_project_id, index=True,
        compute='_compute_project_id', store=True, readonly=False)

    so_line = fields.Many2one(compute="_compute_so_line", store=True, readonly=False,default=False,
                              domain=_domain_so_line, falsy_value_label="Non-billable",
                              help="Sales order item to which the time spent will be added in order to be invoiced to your customer. Remove the sales order item for the timesheet entry to be non-billable.")
