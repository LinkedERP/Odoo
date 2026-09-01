from odoo.tests import common


class TestFollowupEmailReceivers(common.TransactionCase):
    """The follow-up reminder receivers are res.partner records picked by email.

    Typing an address in the many2many_tags widget goes through
    ``res.partner.name_create`` with the ``followup_receiver`` context key:
    existing partners are reused (no duplicates), and new addresses create a
    standalone partner. The email is then sent as ONE mail to all receivers.
    """

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Customer A',
            'email': 'billing@customer.com',
            'is_company': True,
        })

    def _name_create(self, name):
        return self.env['res.partner'].with_context(followup_receiver=True).name_create(name)

    def _send_email(self):
        template = self.env.ref('account_followup.email_template_followup_1')
        return self.env['account.followup.report']._send_email({
            'partner_id': self.partner.id,
            'mail_template': template,
        })

    def test_new_email_creates_standalone_partner(self):
        partner_id, _ = self._name_create('custom1@test.com')
        created = self.env['res.partner'].browse(partner_id)

        self.assertEqual(created.email, 'custom1@test.com')
        self.assertFalse(created.parent_id)

    def test_existing_email_reuses_partner(self):
        existing = self.env['res.partner'].create({
            'name': 'Already There',
            'email': 'custom1@test.com',
        })

        partner_id, _ = self._name_create('custom1@test.com')

        self.assertEqual(partner_id, existing.id)
        self.assertEqual(
            self.env['res.partner'].search_count([('email', '=', 'custom1@test.com')]), 1,
        )

    def test_send_email_sends_one_mail_to_all_receivers(self):
        custom1 = self.env['res.partner'].create({'name': 'Custom 1', 'email': 'custom1@test.com'})
        custom2 = self.env['res.partner'].create({'name': 'Custom 2', 'email': 'custom2@test.com'})
        self.partner.followup_email_receivers = [(6, 0, [custom1.id, custom2.id])]

        self._send_email()

        mails = self.env['mail.mail'].search([('email_to', 'ilike', 'custom1@test.com')])
        self.assertEqual(len(mails), 1)
        self.assertIn('custom2@test.com', mails.email_to)
        self.assertIn('custom1@test.com', mails.email_to)

    def test_send_email_does_not_notify_the_partner_itself(self):
        """Receivers replace the billing contact, they do not extend it."""
        custom1 = self.env['res.partner'].create({'name': 'Custom 1', 'email': 'custom1@test.com'})
        self.partner.followup_email_receivers = [(6, 0, [custom1.id])]

        self._send_email()

        mails = self.env['mail.mail'].search([('email_to', 'ilike', 'custom1@test.com')])
        self.assertEqual(len(mails), 1)
        self.assertNotIn('billing@customer.com', mails.email_to)

    def test_manual_reminder_wizard_shows_receivers(self):
        custom1 = self.env['res.partner'].create({'name': 'Custom 1', 'email': 'custom1@test.com'})
        self.partner.followup_email_receivers = [(6, 0, [custom1.id])]

        wizard = self.env['account_followup.manual_reminder'].with_context(
            active_model='res.partner', active_ids=self.partner.ids
        ).create({'partner_id': self.partner.id})

        self.assertEqual(wizard.email_recipient_ids, custom1)

    def test_receivers_keep_input_order(self):
        """Order must match what was typed, not the partners' own id order."""
        custom1 = self.env['res.partner'].create({'name': 'Custom 1', 'email': 'custom1@test.com'})
        custom2 = self.env['res.partner'].create({'name': 'Custom 2', 'email': 'custom2@test.com'})

        # custom1.id < custom2.id, but typed in the reverse order.
        self.partner.followup_email_receivers = [(6, 0, [custom2.id, custom1.id])]

        self.assertEqual(self.partner.followup_email_receivers.ids, [custom2.id, custom1.id])

    def test_empty_field_falls_back_to_partner(self):
        self._send_email()

        mails = self.env['mail.mail'].search([('recipient_ids', 'in', self.partner.id)])
        self.assertEqual(len(mails), 1)
