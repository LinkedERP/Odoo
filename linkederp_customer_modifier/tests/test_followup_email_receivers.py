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

    def test_receiver_partners_resolved(self):
        self.partner.followup_email_receivers = 'custom1@test.com, custom2@test.com'
        receivers = self.partner._get_followup_email_receiver_partners()
        self.assertEqual(len(receivers), 2)
        self.assertEqual(set(receivers.mapped('email')), {'custom1@test.com', 'custom2@test.com'})

    def test_manual_reminder_wizard_recipients_override(self):
        self.partner.followup_email_receivers = 'custom1@test.com'
        wizard = self.env['account_followup.manual_reminder'].with_context(
            active_model='res.partner', active_ids=self.partner.ids
        ).create({'partner_id': self.partner.id})
        wizard._compute_email_recipient_ids()
        self.assertEqual(len(wizard.email_recipient_ids), 1)
        self.assertEqual(wizard.email_recipient_ids.email, 'custom1@test.com')

    def test_invalid_email_rejected(self):
        with self.assertRaises(ValidationError):
            self.partner.followup_email_receivers = 'not-an-email, valid@test.com'

    def test_send_email_batches_all_receivers_into_one_email(self):
        self.partner.followup_email_receivers = 'custom1@test.com, custom2@test.com'
        template = self.env.ref('account_followup.email_template_followup_1')
        receivers = self.partner._get_followup_email_receiver_partners()

        self.env['account.followup.report']._send_email({
            'partner_id': self.partner.id,
            'mail_template': template,
        })

        mails = self.env['mail.mail'].search([('recipient_ids', 'in', receivers.ids)])
        self.assertEqual(len(mails), 1)
        self.assertEqual(set(mails.recipient_ids.ids), set(receivers.ids))
