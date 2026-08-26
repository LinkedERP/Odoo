from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.tools.mail import email_normalize


class ResPartner(models.Model):
    _inherit = 'res.partner'

    followup_email_receivers = fields.Char(
        string='Follow-up Email Receivers',
        groups='account.group_account_invoice',
        help='Comma-separated list of email addresses that will receive the payment follow-up '
             'reminders, instead of the billing (invoice) contact. Leave empty to fall back to '
             'the default invoice address.',
    )

    @api.constrains('followup_email_receivers')
    def _check_followup_email_receivers(self):
        for partner in self:
            if not partner.followup_email_receivers:
                continue
            invalid = [
                token.strip()
                for token in partner.followup_email_receivers.split(',')
                if token.strip() and not email_normalize(token.strip(), strict=True)
            ]
            if invalid:
                raise ValidationError(
                    _("Invalid email address(es) in Follow-up Email Receivers: %s", ', '.join(invalid))
                )
