from odoo import fields, models


class AccountFollowupManualReminder(models.TransientModel):
    _inherit = 'account_followup.manual_reminder'

    # 'Extra Recipients' is a many2many to res.partner, so plain addresses can never
    # appear there as chips. Show them as readonly text next to it instead.
    # ponytail: no partner is created just to render a chip.
    followup_email_receivers = fields.Char(related='partner_id.followup_email_receivers')
