from odoo import _, api, models

from odoo.tools.mail import email_normalize_all


class AccountFollowupReport(models.AbstractModel):
    _inherit = 'account.followup.report'

    @api.model
    def _send_email(self, options):
        """When ``followup_email_receivers`` is set, send ONE email to all of them.

        The receivers are plain email addresses, not res.partner records, so they
        are passed via ``outgoing_email_to`` instead of ``partner_ids`` — this
        keeps them out of the partner list entirely.
        """
        partner = self.env['res.partner'].browse(options.get('partner_id'))
        receivers = email_normalize_all(partner.followup_email_receivers)
        if not receivers:
            return super()._send_email(options)

        followup_line = options.get('followup_line', partner.followup_line_id)
        self = self.with_context(lang=partner.lang or self.env.user.lang)
        body_html = self.with_context(mail=True).get_followup_report_html(options)
        author_id = options.get('author_id', partner._get_followup_responsible().partner_id.id)

        partner.with_context(mail_post_autofollow=True, lang=partner.lang or self.env.user.lang).message_post(
            outgoing_email_to=', '.join(receivers),
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
