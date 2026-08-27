from odoo import api, fields, models

class AccountFollowupManualReminder(models.TransientModel):
    _inherit = 'account_followup.manual_reminder'

    # 'Extra Recipients' is a many2many to res.partner, so plain addresses can never
    # appear there as chips. Show them as readonly text next to it instead.
    # ponytail: no partner is created just to render a chip.
    followup_email_receivers = fields.Char(related='partner_id.followup_email_receivers')

    @api.depends('template_id')
    def _compute_email_recipient_ids(self):
        super()._compute_email_recipient_ids()
        # Receivers replace the partner contacts, they don't extend them — keep the
        # wizard honest so it shows what _send_email will actually do.
        self.filtered('followup_email_receivers').email_recipient_ids = False
