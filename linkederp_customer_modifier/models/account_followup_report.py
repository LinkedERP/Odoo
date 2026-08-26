from odoo import _, api, models


class AccountFollowupReport(models.AbstractModel):
    _inherit = 'account.followup.report'

    @api.model
    def _send_email(self, options):
        """When ``followup_email_receivers`` is set, send ONE email to all of them.

        The stock implementation loops over ``_get_email_recipients`` and calls
        ``message_post`` once per recipient, which results in one separate email
        per address. Here all receivers are passed to a single ``message_post``
        call instead, so they land in the same outgoing email (same notification
        group + lang, batched into one ``mail.mail`` by the mail thread layer).
        """
        partner = self.env['res.partner'].browse(options.get('partner_id'))
        receivers = partner._get_followup_email_receiver_partners()
        if not receivers:
            return super()._send_email(options)

        followup_line = options.get('followup_line', partner.followup_line_id)
        self = self.with_context(lang=partner.lang or self.env.user.lang)
        body_html = self.with_context(mail=True).get_followup_report_html(options)
        author_id = options.get('author_id', partner._get_followup_responsible().partner_id.id)

        partner.with_context(mail_post_autofollow=True, lang=partner.lang or self.env.user.lang).message_post(
            partner_ids=receivers.ids,
            author_id=author_id,
            email_from=self._get_email_from(options),
            body=body_html,
            subject=self._get_email_subject(options),
            reply_to=self._get_email_reply_to(options),
            model_description=_('payment reminder'),
            notify_author=True,
            email_layout_xmlid='mail.mail_notification_light',
            attachment_ids=options.get('attachment_ids'),
            subtype_id=self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
        )

        if followup_line and followup_line.additional_follower_ids:
            partner.message_subscribe(followup_line.additional_follower_ids.partner_id.ids)
