from odoo import models, fields

class HelpdeskTicketReportAnalysis(models.Model):
    _inherit = 'helpdesk.ticket.report.analysis'

    task_type = fields.Selection([
        ('service_request', 'Service Request'),
        ('change_request', 'Change Request'),
    ], string='Task Type', readonly=True)

    def _select(self):
        select_str = super()._select()
        select_str += ", t.task_type as task_type"
        return select_str

    def _group_by(self):
        group_by_str = super()._group_by()
        group_by_str += ", t.task_type"
        return group_by_str
