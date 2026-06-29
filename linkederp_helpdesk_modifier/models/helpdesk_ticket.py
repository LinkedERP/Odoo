import json
import logging
from datetime import timedelta, datetime, date as date_type
from odoo import models, fields, api, _
_logger = logging.getLogger(__name__)
REMINDER_DAYS = 3  # Send reminder after this many working days without a response

class HelpdeskTicket(models.Model):
    """Extend helpdesk ticket with auto email reminder logic."""
    _inherit = 'helpdesk.ticket'

    available_sale_line_domain = fields.Char(
        compute='_compute_available_sale_line_domain',
    )

    @api.depends('sale_order_id')
    def _compute_available_sale_line_domain(self):
        for ticket in self:
            so = ticket.sale_order_id
            if so:
                ticket.available_sale_line_domain = json.dumps([
                    ('id', 'in', so.order_line.ids)
                ])
            else:
                ticket.available_sale_line_domain = json.dumps([])

    sale_line_id = fields.Many2one(
        'sale.order.line', string="Sales Order Item", tracking=True,
        compute="_compute_sale_line_id", store=True, readonly=False,
        domain="available_sale_line_domain",
        help="Sales Order Item to which the time spent on this ticket will be added in order to be invoiced to your customer.\n"
             "By default the last prepaid sales order item that has time remaining will be selected.\n"
             "Remove the sales order item in order to make this ticket non-billable.\n"
             "You can also change or remove the sales order item of each timesheet entry individually.")

    last_reminder_sent = fields.Date(
        string='Last Reminder Sent',
        help='Date when the last unanswered ticket reminder was sent.',
        copy=False,
    )

    # -------------------------------------------------------------------------
    # Cron method - called by the scheduled action daily
    # -------------------------------------------------------------------------
    @api.model
    def _cron_send_unanswered_ticket_reminders(self):
        """
        Find open helpdesk tickets that have had no reply from the support team
        for more than REMINDER_DAYS working days (per user calendar) and send an email reminder.
        """
        open_tickets = self.search([
            ('stage_id.fold', '=', False),
            ('user_id', '!=', False),
        ])
        reminder_template = self.env.ref(
            'linkederp_helpdesk_modifier.helpdesk_ticket_reminder_template',
            raise_if_not_found=False,
        )
        if not reminder_template:
            _logger.warning(
                'LinkedERP Helpdesk Modifier: reminder mail template not found. '
                'Skipping reminder cron.'
            )
            return
        tickets_to_remind = self.env['helpdesk.ticket']
        for ticket in open_tickets:
            # Get calendar from employee user, fallback to company calendar
            employee = ticket.user_id.employee_id if ticket.user_id else False
            calendar = (
                employee.resource_calendar_id
                if employee and employee.resource_calendar_id
                else self.env.company.resource_calendar_id
            )
            threshold = self._get_n_working_days_ago_per_calendar(REMINDER_DAYS, calendar)

            # Skip if a reminder was already sent within the last 3 working days
            if ticket.last_reminder_sent:
                last_sent_dt: datetime = datetime.combine(ticket.last_reminder_sent, datetime.min.time())
                if last_sent_dt >= threshold:
                    continue

            if self._ticket_has_no_recent_support_reply(ticket, threshold):
                tickets_to_remind = tickets_to_remind + ticket

        for ticket in tickets_to_remind:
            recipients = self._get_reminder_recipients(ticket)
            if not recipients:
                continue

            email_to = ','.join(filter(None, recipients.mapped('email')))
            if not email_to:
                continue

            # Render subject & body from template
            subject = reminder_template._render_field('subject', ticket.ids)[ticket.id]
            body = reminder_template._render_field('body_html', ticket.ids)[ticket.id]

            # 1. Send email via template
            reminder_template.with_context(
                mail_auto_thread=False,
            ).send_mail(
                ticket.id,
                force_send=True,
                raise_exception=False,
                email_values={
                    'email_to': email_to,
                    'recipient_ids': [],
                },
            )

            # 2. Post chatter manual - 1 chatter
            ticket.message_post(
                subject=subject,
                body=body,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
                author_id=self.env.user.partner_id.id,
            )

            # 3. Record the date of this reminder using direct SQL.
            # IMPORTANT: Must NOT use write() here because it updates write_date,
            # which would cause _ticket_has_no_recent_support_reply to skip this
            # ticket on future cron runs, preventing any further reminders.
            self.env.cr.execute(
                "UPDATE helpdesk_ticket SET last_reminder_sent = %s WHERE id = %s",
                (fields.Date.today(), ticket.id)
            )
            ticket.invalidate_recordset(['last_reminder_sent'])
            _logger.info(
                'Sent reminder for ticket %s (id=%d) to %s',
                ticket.name, ticket.id, email_to,
            )

    @api.model
    def _get_n_working_days_ago_per_calendar(self, n, calendar):
        """
        Return a datetime representing n working days ago from now,
        excluding weekends (Saturday/Sunday) and public holidays from the given calendar.
        """
        current: datetime = fields.Datetime.now()
        days_counted = 0
        public_holidays: set = set()
        if calendar:
            leaves = self.env['resource.calendar.leaves'].search([
                ('calendar_id', '=', calendar.id),
                ('resource_id', '=', False),
                ('date_from', '!=', False),
                ('date_to', '!=', False),
            ])
            for leave in leaves:
                date_from: date_type = fields.Date.from_string(leave.date_from)
                date_to: date_type = fields.Date.from_string(leave.date_to)
                if not date_from or not date_to:
                    continue
                d: date_type = date_from
                while d <= date_to:
                    public_holidays.add(d)
                    d += timedelta(days=1)
        while days_counted < n:
            current = current - timedelta(days=1)
            assert isinstance(current, datetime)
            is_weekday = current.weekday() < 5
            is_public_holiday = current.date() in public_holidays
            if is_weekday and not is_public_holiday:
                days_counted += 1
        return current

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _ticket_has_no_recent_support_reply(self, ticket, threshold):
        """
        Return True if the ticket has NOT received any message from a support
        team member (internal user in the team) since the given threshold datetime.

        A ticket is considered 'unanswered' when:
          - Its last update (write_date) is before the threshold date, AND
          - There is no message posted by a team member (or the assigned user)
            after the threshold date.
        """
        # Use write_date (last update) if available, fallback to create_date
        last_update = ticket.write_date or ticket.create_date
        if not last_update or last_update >= threshold:
            return False  # Ticket was updated too recently, or has no date - no reminder yet
        # Collect partner IDs of all support team members
        team_partner_ids = ticket.team_id.member_ids.mapped('partner_id').ids if ticket.team_id else []
        assigned_partner_id = ticket.user_id.partner_id.id if ticket.user_id and ticket.user_id.partner_id else False
        support_partner_ids = set(team_partner_ids)
        if assigned_partner_id:
            support_partner_ids.add(assigned_partner_id)
        if not support_partner_ids:
            return False
        # Check if any team member has replied after the threshold
        recent_reply = self.env['mail.message'].search_count([
            ('model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
            ('message_type', 'in', ['comment', 'email', 'email_outgoing']),
            ('author_id', 'in', list(support_partner_ids)),
            ('date', '>=', threshold),
        ], limit=1)
        return recent_reply == 0

    def _get_reminder_recipients(self, ticket):
        """
        Return a res.users recordset of recipients for the reminder:
          - The assigned user (user_id)
          - The project manager of the helpdesk team (team_id.project_id.user_id) [commented out]
        """
        recipients = self.env['res.users']
        if ticket.user_id:
            recipients |= ticket.user_id
        # if ticket.team_id and ticket.team_id.project_id.user_id:
        #     recipients |= ticket.team_id.project_id.user_id
        return recipients
