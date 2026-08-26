from odoo import models


class AccountFollowupManualReminder(models.TransientModel):
    _inherit = 'account_followup.manual_reminder'

    def _compute_email_recipient_ids(self):
        """Show the partner's ``followup_email_receivers`` in the Send wizard.

        Keeps the wizard's 'Extra Recipients' list consistent with the emails the
        follow-up is actually sent to.
        """
        super()._compute_email_recipient_ids()
        for wizard in self:
            receivers = wizard.partner_id._get_followup_email_receiver_partners()
            if receivers:
                wizard.email_recipient_ids = receivers
