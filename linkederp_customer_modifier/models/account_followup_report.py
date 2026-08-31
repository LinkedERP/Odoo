from odoo import _, api, models


class AccountFollowupReport(models.AbstractModel):
    _inherit = 'account.followup.report'

    @api.model
    def _send_email(self, options):
        """When ``followup_email_receivers`` is set, send ONE email to those only.

        The receivers replace the regular contacts (the billing contact / the
        wizard's 'Email Recipients'), not extend them. They are res.partner
        records, so we reuse the native email-only path (``outgoing_email_to``)
        to batch every receiver into a single mail — ``partner_ids`` stays empty
        so the billing contact is not notified.

        The fallback path goes through enterprise code we don't own, so it's
        flagged via the ``followup_keep_sent_email`` context key — see
        ResPartner._notify_thread_by_email.
        """
        partner = self.env['res.partner'].browse(options.get('partner_id'))
        receivers = partner.followup_email_receivers.filtered('email_normalized')
        if not receivers:
            return super(
                AccountFollowupReport, self.with_context(followup_keep_sent_email=True)
            )._send_email(options)

        followup_line = options.get('followup_line', partner.followup_line_id)
        self = self.with_context(lang=partner.lang or self.env.user.lang)
        body_html = self.with_context(mail=True).get_followup_report_html(options)
        author_id = options.get('author_id', partner._get_followup_responsible().partner_id.id)

        partner.with_context(mail_post_autofollow=True, lang=partner.lang or self.env.user.lang).message_post(
            partner_ids=[],
            outgoing_email_to=', '.join(receivers.mapped('email_normalized')),
            mail_auto_delete=False,
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
