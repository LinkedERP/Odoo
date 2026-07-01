# models/project_project.py
from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    x_is_reinvoice_completed = fields.Boolean(
        string='Reinvoice Completed',
        compute='_compute_x_is_reinvoice_completed',
        store=True,
    )

    @api.depends('reinvoiced_sale_order_id.x_studio_completed')
    def _compute_x_is_reinvoice_completed(self):
        # sudo() supaya field reinvoiced_sale_order_id bisa dibaca
        # tanpa perlu group Sales pada user biasa
        for project in self.sudo():
            project.x_is_reinvoice_completed = bool(
                project.reinvoiced_sale_order_id
                and project.reinvoiced_sale_order_id.x_studio_completed
            )