from odoo import api, fields, models
import json

class ProjectTask(models.Model):
    _inherit = "project.task"

    available_sale_line_domain = fields.Char(
        compute="_compute_available_sale_line_domain"
    )

    @api.depends("project_sale_order_id")
    def _compute_available_sale_line_domain(self):
        for task in self:
            if task.project_sale_order_id:
                task.available_sale_line_domain = json.dumps([
                    ("id", "in", task.project_sale_order_id.order_line.ids)
                ])
            else:
                task.available_sale_line_domain = json.dumps([])

    sale_order_completed = fields.Boolean(compute='_compute_sale_order_complete', store=False)

    @api.depends("sale_order_id","project_id")
    def _compute_sale_order_complete(self):
        for task in self:
            if task.project_sale_order_id or task.sale_order_id:
                task.sale_order_completed =  task.sale_order_id.x_studio_completed or task.project_sale_order_id.x_studio_completed

    sale_line_id = fields.Many2one(
        'sale.order.line', 'Sales Order Item',
        copy=True, tracking=True, index='btree_not_null', recursive=True,
        compute='_compute_sale_line', store=True, readonly=False,
        domain='available_sale_line_domain',
        context={'with_remaining_hours': True},
        help="Sales Order Item to which the time spent on this task will be added in order to be invoiced to your customer.\n"
             "By default the sales order item set on the project will be selected. In the absence of one, the last prepaid sales order item that has time remaining will be used.\n"
             "Remove the sales order item in order to make this task non billable. You can also change or remove the sales order item of each timesheet entry individually.")