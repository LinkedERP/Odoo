from odoo.exceptions import ValidationError
from odoo.tests import common


class TestFollowupEmailReceivers(common.TransactionCase):
    """The follow-up reminder email receivers are moved to followup_email_receivers."""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Customer A',
            'email': 'billing@customer.com',
            'is_company': True,
        })

    def test_invalid_email_rejected(self):
        with self.assertRaises(ValidationError):
            self.partner.followup_email_receivers = 'not-an-email, valid@test.com'

    def test_send_email_batches_all_receivers_into_one_email(self):
        self.partner.followup_email_receivers = 'custom1@test.com, custom2@test.com'
        template = self.env.ref('account_followup.email_template_followup_1')

        self.env['account.followup.report']._send_email({
            'partner_id': self.partner.id,
            'mail_template': template,
        })

        mails = self.env['mail.mail'].search([('email_to', 'ilike', 'custom1@test.com')])
        self.assertEqual(len(mails), 1)
        self.assertIn('custom2@test.com', mails.email_to)

    def test_send_email_does_not_create_partners(self):
        self.partner.followup_email_receivers = 'custom1@test.com, custom2@test.com'
        template = self.env.ref('account_followup.email_template_followup_1')
        count_before = self.env['res.partner'].search_count(
            [('email', 'in', ['custom1@test.com', 'custom2@test.com'])])

        self.env['account.followup.report']._send_email({
            'partner_id': self.partner.id,
            'mail_template': template,
        })

        self.assertEqual(
            self.env['res.partner'].search_count([('email', 'in', ['custom1@test.com', 'custom2@test.com'])]),
            count_before,
        )

    def test_manual_reminder_wizard_preview_does_not_create_partners(self):
        self.partner.followup_email_receivers = 'custom1@test.com'
        count_before = self.env['res.partner'].search_count([('email', '=', 'custom1@test.com')])

        wizard = self.env['account_followup.manual_reminder'].with_context(
            active_model='res.partner', active_ids=self.partner.ids
        ).create({'partner_id': self.partner.id})
        wizard._compute_email_recipient_ids()

        self.assertEqual(
            self.env['res.partner'].search_count([('email', '=', 'custom1@test.com')]),
            count_before,
        )

    def test_empty_field_falls_back_to_partner(self):
        template = self.env.ref('account_followup.email_template_followup_1')

        self.env['account.followup.report']._send_email({
            'partner_id': self.partner.id,
            'mail_template': template,
        })

        mails = self.env['mail.mail'].search([('recipient_ids', 'in', self.partner.id)])
        self.assertEqual(len(mails), 1)
