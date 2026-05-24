#!/usr/bin/env python3
"""
Debugging script to check if all components are properly set up in staging.
Run this in Odoo shell: odoo shell -c staging.conf -d staging_db
Then: exec(open('debug_staging.py').read())
"""

from odoo import models
from odoo.tools.misc import find_in_path

print("=" * 70)
print("DEBUGGING: Helpdesk Ticket Reminder Setup")
print("=" * 70)

# 1. Check if template exists
print("\n1. Checking for email template...")
template = env.ref(
    'linkederp_helpdesk_modifier.helpdesk_ticket_reminder_template',
    raise_if_not_found=False
)
if template:
    print("   ✓ Template FOUND: %s" % template.name)
    print("   - ID: %s" % template.id)
    print("   - Subject: %s" % template.subject)
else:
    print("   ✗ Template NOT FOUND - This is the issue!")

# 2. Check if scheduled action exists
print("\n2. Checking for scheduled action (cron)...")
cron = env.ref(
    'linkederp_helpdesk_modifier.ir_cron_helpdesk_ticket_reminder',
    raise_if_not_found=False
)
if cron:
    print("   ✓ Scheduled Action FOUND: %s" % cron.name)
    print("   - Active: %s" % cron.active)
    print("   - Interval: every %d %s" % (cron.interval_number, cron.interval_type))
    print("   - Next call: %s" % cron.nextcall)
else:
    print("   ✗ Scheduled Action NOT FOUND")

# 3. Check if module is installed
print("\n3. Checking module installation...")
module = env['ir.module.module'].search([
    ('name', '=', 'linkederp_helpdesk_modifier')
], limit=1)
if module:
    print("   ✓ Module INSTALLED: %s (state: %s)" % (module.name, module.state))
else:
    print("   ✗ Module NOT INSTALLED")

# 4. Check helpdesk tickets
print("\n4. Checking helpdesk tickets...")
open_tickets = env['helpdesk.ticket'].search([
    ('stage_id.fold', '=', False),
    ('user_id', '!=', False),
])
print("   - Total open assigned tickets: %d" % len(open_tickets))
if open_tickets:
    for ticket in open_tickets[:3]:  # Show first 3
        print("     • %s (assigned to: %s, updated: %s)" % (
            ticket.name,
            ticket.user_id.name,
            ticket.write_date or ticket.create_date
        ))

# 5. Check email configuration
print("\n5. Checking email configuration...")
outgoing = env['ir.mail_server'].search([])
if outgoing:
    print("   ✓ Outgoing mail servers configured: %d" % len(outgoing))
    for server in outgoing:
        print("     • %s (SMTP: %s:%s, Enabled: %s)" % (
            server.name,
            server.smtp_host,
            server.smtp_port,
            server.active
        ))
else:
    print("   ✗ No outgoing mail servers configured!")

# 6. Check company settings
print("\n6. Checking company settings...")
company = env.company
print("   - Company: %s" % company.name)
print("   - Email: %s" % company.email)
print("   - Calendar: %s" % (company.resource_calendar_id.name if company.resource_calendar_id else "Not set"))

print("\n" + "=" * 70)
print("DIAGNOSIS COMPLETE")
print("=" * 70)

