from odoo import models


class AccountFollowupReport(models.AbstractModel):
    _inherit = 'account.followup.report'

    def _get_email_recipients(self, options):
        """Use the partner's ``followup_email_receivers`` as email recipients when set.

        Intercepts before the wizard-provided ``email_recipient_ids`` are returned,
        so both automatic (cron) and manual (Send wizard) follow-ups go to the
        custom receivers.
        """
        partner = self.env['res.partner'].browse(options.get('partner_id'))
        receivers = partner._get_followup_email_receiver_partners()
        if receivers:
            return receivers
        return super()._get_email_recipients(options)
