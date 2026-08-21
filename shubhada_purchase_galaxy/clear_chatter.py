"""Wipe the message history on a record so a take starts with a clean chatter.

    python clear_chatter.py [res_id]

Re-shooting an approval take means cancelling and rewinding the order, and every
one of those rewinds writes itself into the chatter. Left alone, the finished
video shows a column of "Cancelled -> RFQ" entries in the operator's name, which
is the first thing anyone reads on the right-hand side of the screen.
"""
import sys
import odoolib as o

CO = {'allowed_company_ids': [4], 'company_id': 4}
RES_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 246

msgs = o.call('mail.message', 'search',
              [('model', '=', 'purchase.order'), ('res_id', '=', RES_ID)], context=CO)
if msgs:
    o.call('mail.message', 'unlink', msgs, context=CO)
    o.call('mail.tracking.value', 'search', [('mail_message_id', 'in', msgs)], context=CO)
print('  cleared %d chatter message(s) on purchase.order %d' % (len(msgs), RES_ID))
