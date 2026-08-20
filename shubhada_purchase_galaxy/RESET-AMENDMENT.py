"""Put the amendment scenario back to its pre-amendment state.

Run this after any rehearsal or take, so the amendment can be demonstrated live again:

    python RESET-AMENDMENT.py

Restores order SHN27PO04190 (copper, 4,000 kg at Rs 862) to:
    posted, no amendments, both GRNs booked at Rs 862
so the revision to Rs 892 effective 10 August can be done on camera.
"""
import json
import time
import urllib.error
import urllib.request

URL = 'https://linked-staging2.odoo.com/jsonrpc'
DB = 'linkederp-stagingdm-36147382'
# Devang is the Plant Head, which implies HOD - and only an HOD may delete an
# amendment. Running this as Mahesh fails with an access error, correctly.
LOGIN = 'devang@shubhada.demo'
PWD = 'Shubhada@2026'
CTX = {'context': {'allowed_company_ids': [4], 'company_id': 4}}

GALAXY_NUMBER = 'SHN27PO04190'
BASE_RATE = 862.0
_id = [0]


def rpc(service, method, args, timeout=300):
    _id[0] += 1
    body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': _id[0],
                       'params': {'service': service, 'method': method,
                                  'args': args}}).encode()
    j = None
    for attempt in range(10):
        req = urllib.request.Request(URL, body, {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code != 503 or attempt == 9:
                raise
            if attempt == 0:
                print('  instance restarting (503) - waiting...')
            time.sleep(30)
    if 'error' in j:
        d = j['error'].get('data') or {}
        raise RuntimeError((d.get('message') or j['error'].get('message', ''))[:800])
    return j['result']


UID = rpc('common', 'authenticate', [DB, LOGIN, PWD, {}])
if not UID:
    raise SystemExit('login failed for ' + LOGIN)


def c(model, method, *args, **kw):
    return rpc('object', 'execute_kw', [DB, UID, PWD, model, method, list(args), dict(CTX, **kw)])


order = c('purchase.order', 'search_read',
          [('x_galaxy_number', '=', GALAXY_NUMBER)],
          ['id', 'x_approval_state', 'x_amendment_no'], limit=1)
if not order:
    raise SystemExit('%s not found - the scenario has not been built.' % GALAXY_NUMBER)
order = order[0]

# 1. drop any amendments raised against it
amds = c('shubhada.po.amendment', 'search_read',
         [('order_id', '=', order['id'])], ['id', 'name'])
for a in amds:
    c('shubhada.po.amendment', 'unlink', [a['id']])
print('[1/3] removed %d amendment(s): %s'
      % (len(amds), ', '.join(a['name'] for a in amds) or 'none'))

# 2. rate back to the contract rate, on the line and on every receipt
line = c('purchase.order.line', 'search_read',
         [('order_id', '=', order['id'])], ['id', 'price_unit', 'move_ids'])[0]
c('purchase.order.line', 'write', [line['id']], {'price_unit': BASE_RATE})
moves = c('stock.move', 'search_read',
          [('id', 'in', line['move_ids']), ('state', '=', 'done')],
          ['id', 'picking_id', 'quantity', 'price_unit'])
for m in moves:
    c('stock.move', 'write', [m['id']],
      {'price_unit': BASE_RATE, 'value': m['quantity'] * BASE_RATE})
print('[2/3] rate reset to %.2f on the line and %d receipt(s)' % (BASE_RATE, len(moves)))

# 3. order back to posted, no amendment history
c('purchase.order', 'write', [order['id']], {
    'x_approval_state': 'posted',
    'x_galaxy_status': 'open',
    'x_amendment_no': 0,
    'x_amendment_date': False,
})
print('[3/3] order back to Posted, amendment count 0')

line = c('purchase.order.line', 'search_read',
         [('order_id', '=', order['id'])], ['product_qty', 'qty_received', 'price_unit'])[0]
print('\n' + '=' * 64)
print('  %s  ready to amend again' % GALAXY_NUMBER)
print('  %.0f kg @ Rs %.2f   received %.0f   pending %.0f'
      % (line['product_qty'], line['price_unit'], line['qty_received'],
         line['product_qty'] - line['qty_received']))
for m in c('stock.move', 'search_read',
           [('id', 'in', [x['id'] for x in moves])],
           ['picking_id', 'quantity', 'price_unit', 'date'], order='date'):
    print('  %-16s %6.0f kg @ %7.2f   %s'
          % (m['picking_id'][1], m['quantity'], m['price_unit'], m['date'][:10]))
print('  On camera: revise to Rs 892 with effect from 10 Aug -> only the second')
print('  receipt is reached, difference Rs 36,000.')
print('=' * 64)
