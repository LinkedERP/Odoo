from odoo import models, api, _

class DigestCustom(models.Model):
    _inherit = 'digest.digest'

    @api.model
    def _get_mail_body(self, user):
        """Override the digest email body content"""

        # Original body (to retain existing KPIs, optional)
        original_body = super()._get_mail_body(user)

        # Compute custom KPIs
        sale_count = self.env['sale.order'].search_count([('user_id', '=', user.id)])
        lead_count = self.env['crm.lead'].search_count([('user_id', '=', user.id)])
        invoice_count = self.env['account.move'].search_count([
            ('move_type', '=', 'out_invoice'),
            ('invoice_user_id', '=', user.id)
        ])

        # Render custom template (defined in XML)
        custom_body = self.env['ir.qweb']._render(
            'custom_digest_enhancement.custom_digest_body_template',
            {
                'user': user,
                'sale_count': sale_count,
                'lead_count': lead_count,
                'invoice_count': invoice_count,
            }
        )

        # Combine custom + original (or replace original entirely)
        combined_body = custom_body + original_body

        return combined_body
