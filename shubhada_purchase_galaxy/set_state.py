"""Put P00246 into a given approval state, so an approval take can be re-shot.

    python set_state.py draft|submitted|hod_approved

A take that fails the engine's sync check has STILL performed its clicks, so the
order has to be rewound before the take is attempted again.
"""
import sys
import odoolib as o

CO = {'allowed_company_ids': [4], 'company_id': 4}
# tracking_disable stops Odoo logging these rewinds to the chatter. Without it the
# finished video shows a column of 'Cancelled -> RFQ' entries from the re-shoots,
# which is the first thing anyone reads on the right of the screen.
QUIET = dict(CO, tracking_disable=True, mail_create_nolog=True, mail_notrack=True)
PO = 246
SERIAL = 4204
TARGET = (sys.argv[1] if len(sys.argv) > 1 else 'draft')

vals = {
    'x_galaxy_number': False, 'x_galaxy_status': False,
    'x_amendment_no': 0, 'x_amendment_date': False,
    'x_hod_uid': False, 'x_hod_on': False,
    'x_posted_uid': False, 'x_posted_on': False,
    'x_approval_state': 'draft',
}
if TARGET in ('submitted', 'hod_approved'):
    vals['x_approval_state'] = 'submitted'
if TARGET == 'hod_approved':
    # stamp the time as well as the approver - rewinding with only the name left
    # "HOD approved on" blank on screen, while the narration says every step
    # carries a time to the second
    # Odoo stores datetimes in UTC and renders them in the user's timezone, so a
    # local timestamp comes back +5:30 and the approval appears to happen AFTER
    # the posting it precedes.
    import datetime
    when = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=6)).strftime('%Y-%m-%d %H:%M:%S')
    vals.update({'x_approval_state': 'hod_approved',
                 'x_hod_uid': 178, 'x_hod_on': when})

before = o.call('purchase.order', 'search_read', [('id', '=', PO)],
                ['x_approval_state', 'state'], context=CO)[0]
o.call('purchase.order', 'write', [PO], vals, context=QUIET)

if before['state'] not in ('draft', 'sent'):
    try:
        o.call('purchase.order', 'button_cancel', [PO], context=QUIET)
        o.call('purchase.order', 'button_draft', [PO], context=QUIET)
    except Exception as e:
        print('  (odoo state: %s)' % str(e)[:80])

sid = o.call('shubhada.po.series', 'search', [('code', '=', 'PC01')], context=CO)[0]
o.call('shubhada.po.series', 'write', [sid], {'next_serial': SERIAL}, context=CO)

after = o.call('purchase.order', 'search_read', [('id', '=', PO)],
               ['x_approval_state', 'x_galaxy_number'], context=CO)[0]
print('  P00246 %s -> %s (number %s, PC01 next %d)'
      % (before['x_approval_state'], after['x_approval_state'],
         after['x_galaxy_number'] or 'none', SERIAL))
