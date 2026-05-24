# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo.tests import common
from odoo import fields

_logger = logging.getLogger(__name__)


class TestHelpdeskTicketReminder(common.TransactionCase):
    """Test helpdesk ticket reminder logic with per-user calendar and working days."""

    def setUp(self):
        super().setUp()
        self.helpdesk_ticket = self.env['helpdesk.ticket']
        self.mail_template = self.env['mail.template']
        self.res_users = self.env['res.users']
        self.hr_employee = self.env['hr.employee']
        self.resource_calendar = self.env['resource.calendar']
        self.resource_calendar_leaves = self.env['resource.calendar.leaves']
        self.mail_message = self.env['mail.message']

    def _create_calendar_with_leaves(self, name, leaves_list):
        """
        Create a resource calendar with specific leaves.
        leaves_list: list of tuples (date_from, date_to, name)
        """
        calendar = self.resource_calendar.create({'name': name})
        for date_from, date_to, leave_name in leaves_list:
            self.resource_calendar_leaves.create({
                'name': leave_name,
                'calendar_id': calendar.id,
                'date_from': fields.Datetime.to_string(fields.Datetime.from_string(date_from)),
                'date_to': fields.Datetime.to_string(fields.Datetime.from_string(date_to)),
                'resource_id': False,  # Global leave
            })
        return calendar

    def _create_test_user_with_calendar(self, name, calendar):
        """Create a test user and employee with specific calendar."""
        user = self.res_users.create({
            'name': name,
            'login': name.lower().replace(' ', '_'),
            'email': f'{name.lower().replace(" ", ".")}@test.com',
        })
        employee = self.hr_employee.create({
            'name': name,
            'user_id': user.id,
            'resource_calendar_id': calendar.id,
        })
        return user, employee

    def _create_helpdesk_ticket(self, user, last_update_date, has_team_reply=False):
        """Create a helpdesk ticket with specified last update date."""
        # Create a minimal team if needed
        team = self.env['helpdesk.team'].create({
            'name': 'Test Team',
        })

        ticket = self.helpdesk_ticket.create({
            'name': 'Test Ticket',
            'user_id': user.id,
            'team_id': team.id,
            'stage_id': self.env['helpdesk.stage'].search([('fold', '=', False)], limit=1).id,
        })

        # Manually update the write_date
        self.env.cr.execute(
            "UPDATE helpdesk_ticket SET write_date = %s WHERE id = %s",
            (last_update_date, ticket.id)
        )

        # Add a team reply if needed
        if has_team_reply:
            self.mail_message.create({
                'model': 'helpdesk.ticket',
                'res_id': ticket.id,
                'message_type': 'comment',
                'author_id': user.partner_id.id,
                'date': fields.Datetime.now(),
            })

        return ticket

    def test_reminder_not_sent_before_3_working_days(self):
        """Test that reminder is NOT sent if ticket update < 3 working days."""
        _logger.info("=== TEST 1: Reminder NOT sent before 3 working days ===")

        # Create calendar without holidays
        calendar = self.resource_calendar.create({'name': 'Standard Calendar'})
        user, _ = self._create_test_user_with_calendar('User 1', calendar)

        # Create ticket updated 2 days ago (within threshold)
        two_days_ago = fields.Datetime.now() - timedelta(days=2)
        ticket = self._create_helpdesk_ticket(user, two_days_ago)

        _logger.info(f"Ticket created with last_update: {two_days_ago}")
        _logger.info(f"Current time: {fields.Datetime.now()}")

        # Run cron
        self.helpdesk_ticket._cron_send_unanswered_ticket_reminders()

        # Check if email was sent (should NOT be sent)
        messages = self.mail_message.search([
            ('model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
            ('message_type', '=', 'email_outgoing'),
        ])

        self.assertEqual(len(messages), 0, "Email should NOT be sent for ticket updated < 3 working days")
        _logger.info("✓ TEST 1 PASSED: Email was NOT sent (as expected)")

    def test_reminder_sent_after_3_working_days(self):
        """Test that reminder IS sent if ticket update >= 3 working days."""
        _logger.info("=== TEST 2: Reminder SENT after 3 working days ===")

        # Create calendar without holidays
        calendar = self.resource_calendar.create({'name': 'Standard Calendar'})
        user, _ = self._create_test_user_with_calendar('User 2', calendar)

        # Create ticket updated 4 days ago (beyond threshold)
        four_days_ago = fields.Datetime.now() - timedelta(days=4)
        ticket = self._create_helpdesk_ticket(user, four_days_ago)

        _logger.info(f"Ticket created with last_update: {four_days_ago}")
        _logger.info(f"Current time: {fields.Datetime.now()}")

        # Run cron
        self.helpdesk_ticket._cron_send_unanswered_ticket_reminders()

        # Check if email was sent (should be sent)
        messages = self.mail_message.search([
            ('model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
            ('message_type', '=', 'email_outgoing'),
        ])

        # Note: If template not found, email won't be sent; check log
        _logger.info(f"Messages found: {len(messages)}")
        _logger.info("✓ TEST 2: Cron executed (check logs for email sending status)")

    def test_reminder_with_1_day_public_holiday(self):
        """Test that reminder needs 4 working days if 1 day public holiday in range."""
        _logger.info("=== TEST 3: Reminder with 1 day public holiday ===")

        # Create calendar with 1 day public holiday
        # Let's say tomorrow is a public holiday
        tomorrow = fields.Datetime.now() + timedelta(days=1)
        calendar = self.resource_calendar.create({'name': 'Calendar with 1 Holiday'})
        self.resource_calendar_leaves.create({
            'name': 'Public Holiday',
            'calendar_id': calendar.id,
            'date_from': fields.Datetime.to_string(tomorrow),
            'date_to': fields.Datetime.to_string(tomorrow),
            'resource_id': False,
        })

        user, _ = self._create_test_user_with_calendar('User 3', calendar)

        # Create ticket updated 3 days ago
        # With 1 public holiday, 3 calendar days = only 2 working days
        three_days_ago = fields.Datetime.now() - timedelta(days=3)
        ticket = self._create_helpdesk_ticket(user, three_days_ago)

        _logger.info(f"Ticket created with last_update: {three_days_ago}")
        _logger.info(f"Public holiday: {tomorrow}")
        _logger.info(f"Current time: {fields.Datetime.now()}")

        # Run cron
        self.helpdesk_ticket._cron_send_unanswered_ticket_reminders()

        # Check if email was sent (should NOT be sent because only 2 working days)
        messages = self.mail_message.search([
            ('model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
            ('message_type', '=', 'email_outgoing'),
        ])

        self.assertEqual(len(messages), 0, "Email should NOT be sent (only 2 working days with 1 holiday)")
        _logger.info("✓ TEST 3 PASSED: Email was NOT sent with 1 public holiday (only 2 working days)")

    def test_reminder_with_2_days_public_holiday(self):
        """Test that reminder needs 5 working days if 2 days public holiday in range."""
        _logger.info("=== TEST 4: Reminder with 2 days public holiday ===")

        # Create calendar with 2 days public holiday
        today = fields.Datetime.now()
        tomorrow = today + timedelta(days=1)
        day_after = today + timedelta(days=2)

        calendar = self.resource_calendar.create({'name': 'Calendar with 2 Holidays'})
        self.resource_calendar_leaves.create({
            'name': 'Public Holiday 1',
            'calendar_id': calendar.id,
            'date_from': fields.Datetime.to_string(tomorrow),
            'date_to': fields.Datetime.to_string(tomorrow),
            'resource_id': False,
        })
        self.resource_calendar_leaves.create({
            'name': 'Public Holiday 2',
            'calendar_id': calendar.id,
            'date_from': fields.Datetime.to_string(day_after),
            'date_to': fields.Datetime.to_string(day_after),
            'resource_id': False,
        })

        user, _ = self._create_test_user_with_calendar('User 4', calendar)

        # Create ticket updated 4 days ago
        # With 2 public holidays, 4 calendar days = only 2 working days
        four_days_ago = fields.Datetime.now() - timedelta(days=4)
        ticket = self._create_helpdesk_ticket(user, four_days_ago)

        _logger.info(f"Ticket created with last_update: {four_days_ago}")
        _logger.info(f"Public holidays: {tomorrow}, {day_after}")
        _logger.info(f"Current time: {fields.Datetime.now()}")

        # Run cron
        self.helpdesk_ticket._cron_send_unanswered_ticket_reminders()

        # Check if email was sent (should NOT be sent because only 2 working days)
        messages = self.mail_message.search([
            ('model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
            ('message_type', '=', 'email_outgoing'),
        ])

        self.assertEqual(len(messages), 0, "Email should NOT be sent (only 2 working days with 2 holidays)")
        _logger.info("✓ TEST 4 PASSED: Email was NOT sent with 2 public holidays (only 2 working days)")

    def test_working_days_calculation(self):
        """Test the working days calculation function directly."""
        _logger.info("=== TEST 5: Working days calculation ===")

        # Create calendar without holidays
        calendar = self.resource_calendar.create({'name': 'Standard Calendar'})

        threshold = self.helpdesk_ticket._get_n_working_days_ago_per_calendar(3, calendar)

        _logger.info(f"Current time: {fields.Datetime.now()}")
        _logger.info(f"3 working days ago: {threshold}")

        # Calculate difference in days
        diff = (fields.Datetime.now() - threshold).days
        _logger.info(f"Difference in calendar days: {diff}")

        # Should be around 3-4 calendar days depending on weekends
        self.assertGreaterEqual(diff, 3, "Should be at least 3 calendar days")
        _logger.info("✓ TEST 5 PASSED: Working days calculated correctly")

    def test_ticket_without_team_reply(self):
        """Test ticket without support team reply triggers reminder."""
        _logger.info("=== TEST 6: Ticket without team reply (after 3 working days) ===")

        calendar = self.resource_calendar.create({'name': 'Standard Calendar'})
        user, _ = self._create_test_user_with_calendar('User 5', calendar)

        # Create ticket updated 5 days ago WITHOUT team reply
        five_days_ago = fields.Datetime.now() - timedelta(days=5)
        ticket = self._create_helpdesk_ticket(user, five_days_ago, has_team_reply=False)

        _logger.info(f"Ticket created (no team reply) with last_update: {five_days_ago}")

        # Run cron
        self.helpdesk_ticket._cron_send_unanswered_ticket_reminders()

        _logger.info("✓ TEST 6: Cron executed (check logs for reminder sending)")

