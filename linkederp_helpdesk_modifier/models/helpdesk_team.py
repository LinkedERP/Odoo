from odoo import models, fields
class HelpdeskTeam(models.Model):
    """Add Project Manager field to Helpdesk Team."""
    _inherit = 'helpdesk.team'
    project_manager_id = fields.Many2one(
        'res.users',
        string='Project Manager',
        help='The project manager responsible for this helpdesk team. '
             'They will receive reminder emails for unanswered tickets.',
        domain=lambda self: "[('all_group_ids', 'in', %d), ('company_ids', 'in', [company_id])]"
                            % self.env.ref('base.group_user').id,
    )
