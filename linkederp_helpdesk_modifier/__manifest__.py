{
    'name': 'LinkedERP Helpdesk Modifier',
    'version': '1.1.1',
    'summary': 'Auto email reminder for unanswered helpdesk tickets after 3 days',
    'description': """
LinkedERP Helpdesk Modifier
===========================

Automated follow-up for stale helpdesk tickets, plus task and billing links:

* Daily reminder emails for open, assigned tickets with no support reply for
  3+ working days, counted per the assignee's resource calendar (weekends and
  public holidays excluded) and gated against re-sending.
* Reminder also posted as an internal note on the ticket.
* Project Manager field on the Helpdesk Team.
* Ticket -> Task roll-up (A05): teams define a default roll-up task, inherited
  and editable per ticket, so ticket effort is visible at task level.
* SO line scoped to the linked order; timesheets locked once the order is completed.
""",
    'category': 'Helpdesk',
    'author': 'LinkedERP',
    'website': 'https://linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'helpdesk',
        'helpdesk_sale',
        'mail',
        'hr_timesheet',
        'helpdesk_sale_timesheet',
    ],
    'data': [
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/helpdesk_team_views.xml',
        'views/helpdesk_ticket_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
