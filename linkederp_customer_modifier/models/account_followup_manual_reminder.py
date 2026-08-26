from odoo import models

from odoo.tools.mail import email_normalize_all


class AccountFollowupManualReminder(models.TransientModel):
    _inherit = 'account_followup.manual_reminder'

    def _compute_email_recipient_ids(self):
        """Preview the partner's ``followup_email_receivers`` in the Send wizard.

        'Extra Recipients' is a many2many to res.partner (stock field), so only
        addresses that already have a matching partner can be shown as a chip here.
        # ponytail: search-only, never creates a partner just to fill this preview.
        The actual send doesn't depend on this field for followup receivers — see
        AccountFollowupReport._send_email, which emails the raw addresses directly.
        """
        super()._compute_email_recipient_ids()
        for wizard in self:
            emails = email_normalize_all(wizard.partner_id.followup_email_receivers)
            if emails:
                wizard.email_recipient_ids = self.env['res.partner'].search([('email', 'in', emails)])
