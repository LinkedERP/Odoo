from odoo import models, fields

class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    task_type = fields.Selection([
        ('service_request', 'Service Request'),
        ('change_request', 'Change Request'),
    ], string='Task Type', default='service_request')
