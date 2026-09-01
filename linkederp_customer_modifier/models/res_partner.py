import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _notify_thread_by_email(self, message, recipients_data, *, msg_vals=False,
                                mail_auto_delete=True, **kwargs):
        # Keep sent follow-up reminder emails (mail.mail) instead of deleting them.
        # The fallback path of AccountFollowupReport._send_email builds its
        # message_post kwargs in enterprise code we don't own, so it flags the flow
        # via the 'followup_keep_sent_email' context key; the custom-receiver path
        # passes mail_auto_delete=False directly and is unaffected here.
        if self.env.context.get('followup_keep_sent_email'):
            mail_auto_delete = False
        return super()._notify_thread_by_email(
            message, recipients_data, msg_vals=msg_vals, mail_auto_delete=mail_auto_delete, **kwargs)

    # Odoo reads a plain many2many back ordered by the comodel's own _order
    # (res.partner: 'id'), not by insertion order — so typed order gets lost
    # on reload. followup_email_receiver_ids/_order below are the real
    # storage; this field reorders them to match how they were typed.
    followup_email_receivers = fields.Many2many(
        'res.partner',
        string='Follow-up Email Receivers',
        compute='_compute_followup_email_receivers',
        inverse='_inverse_followup_email_receivers',
        groups='account.group_account_invoice',
        help='Contacts that will receive the payment follow-up reminders, instead of the '
             'billing (invoice) contact. Leave empty to fall back to the default invoice '
             'address.',
    )
    followup_email_receiver_ids = fields.Many2many(
        'res.partner', 'followup_email_receiver_rel', 'partner_id', 'receiver_id',
        groups='account.group_account_invoice',
    )
    followup_email_receivers_order = fields.Char(default='[]', groups='account.group_account_invoice')

    @api.depends('followup_email_receiver_ids', 'followup_email_receivers_order')
    def _compute_followup_email_receivers(self):
        for partner in self:
            raw_ids = partner.followup_email_receiver_ids.ids
            try:
                order = json.loads(partner.followup_email_receivers_order or '[]')
            except ValueError:
                order = []
            # Keep the tracked order; append anything untracked (legacy data,
            # or a write that bypassed the inverse) at the end.
            ordered = [i for i in order if i in raw_ids] + [i for i in raw_ids if i not in order]
            partner.followup_email_receivers = [(6, 0, ordered)]

    def _inverse_followup_email_receivers(self):
        for partner in self:
            ids = partner.followup_email_receivers.ids
            partner.followup_email_receiver_ids = [(6, 0, ids)]
            partner.followup_email_receivers_order = json.dumps(ids)

    @api.model
    def name_create(self, name):
        # Typing an email in the followup_email_receivers widget must reuse an
        # existing partner with that email rather than create a duplicate.
        # Gated by context so it only affects that one field's quick-create.
        if self.env.context.get('followup_receiver'):
            partner = self.find_or_create(name)
            return partner.id, partner.display_name
        return super().name_create(name)

    @api.constrains('followup_email_receivers')
    def _check_followup_email_receivers(self):
        for partner in self:
            invalid = partner.followup_email_receivers.filtered(lambda p: not p.email_normalized)
            if invalid:
                raise ValidationError(
                    _("Follow-up Email Receivers must have a valid email address: %s",
                      ', '.join(invalid.mapped('display_name')))
                )
