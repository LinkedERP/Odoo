from odoo import api, models


class AccountFollowupManualReminder(models.TransientModel):
    _inherit = 'account_followup.manual_reminder'

    @api.depends('template_id', 'partner_id.followup_email_receivers')
    def _compute_email_recipient_ids(self):
        super()._compute_email_recipient_ids()
        # Receivers replace the partner contacts — keep the wizard honest so it
        # shows what _send_email will actually do. Still editable by the user.
        for wizard in self:
            if wizard.partner_id.followup_email_receivers:
                wizard.email_recipient_ids = wizard.partner_id.followup_email_receivers
