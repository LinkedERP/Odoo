import logging
from datetime import timedelta
from odoo import models, fields, api, _
_logger = logging.getLogger(__name__)
REMINDER_DAYS = 3  # Send reminder after this many days without a response
class HelpdeskTicket(models.Model):
    """Extend helpdesk ticket with auto email reminder logic."""
    _inherit = 'helpdesk.ticket'
    # -------------------------------------------------------------------------
    # Cron method - called by the scheduled action daily
    # -------------------------------------------------------------------------
    @api.model
    def _cron_send_unanswered_ticket_reminders(self):
        """
        Find open helpdesk tickets that have had no reply from the support team
        for more than REMINDER_DAYS days and send an email reminder to the
        assigned user and to the project manager of the helpdesk team.
        """
        threshold = fields.Datetime.now() - timedelta(days=REMINDER_DAYS)
        # Fetch open (non-folded) tickets that are assigned to a user
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
            if self._ticket_has_no_recent_support_reply(ticket, threshold):
                tickets_to_remind = tickets_to_remind + ticket
        for ticket in tickets_to_remind:
            _logger.info(
                'Sending helpdesk ticket reminder for ticket %s (id=%d)',
                ticket.name, ticket.id,
            )
            recipients = self._get_reminder_recipients(ticket)
            if recipients:
                email_to = ','.join(filter(None, recipients.mapped('email')))
                if not email_to:
                    _logger.warning(
                        'No email address found for recipients of ticket %s (id=%d), skipping.',
                        ticket.name, ticket.id,
                    )
                    continue
                reminder_template.send_mail(
                    ticket.id,
                    force_send=True,
                    raise_exception=False,
                    email_values={
                        'email_to': email_to,
                        'recipient_ids': [],  # prevent sending to partners
                    },
                )
    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _ticket_has_no_recent_support_reply(self, ticket, threshold):
        """
        Return True if the ticket has NOT received any message from a support
        team member (internal user in the team) since *threshold*.
        A ticket is considered 'unanswered' when:
          - It was created before the threshold date, AND
          - There is no message posted by a team member (or the assigned user)
            after the threshold date.
        """
        if ticket.create_date >= threshold:
            return False  # Ticket is too new - no reminder yet
        # Collect partner ids of all support team members
        team_partner_ids = ticket.team_id.member_ids.mapped('partner_id').ids
        assigned_partner_id = ticket.user_id.partner_id.id if ticket.user_id else False
        support_partner_ids = set(team_partner_ids)
        if assigned_partner_id:
            support_partner_ids.add(assigned_partner_id)
        if not support_partner_ids:
            return False
        # Look for any message from a team member after the threshold
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
        Return a res.users recordset with the recipients for the reminder:
          - The assigned user (user_id)
          - The project manager of the helpdesk team (team_id.project_id.user_id)
        """
        recipients = self.env['res.users']
        if ticket.user_id:
            recipients |= ticket.user_id
        if ticket.team_id.project_id.user_id:
            recipients |= ticket.team_id.project_id.user_id
        return recipients
