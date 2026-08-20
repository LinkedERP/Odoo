"""Cast the actors and give the Galaxy demo some history.

Run AFTER SEED-GALAXY-PO.py, and after pushing module version 19.0.1.0.3:

    python ENRICH-GALAXY-PO.py

Three jobs:
  1. Put people in the new groups. Without this NOBODY can see the Approve or
     Post buttons, because those buttons are group-restricted.
  2. A confirmed order from last month at OLDER rates, so "Last Purchased Rate"
     on the live order shows a real number to compare against instead of 0.00.
  3. A Local Capital order that the bought-out buyer is not allowed to see, so
     the series segregation can actually be demonstrated - plus a delivery
     schedule on every line of the live draft.

Idempotent: it checks before it creates.

CAST
    Mahesh Joshi      raises bought-out orders   (cannot see capital orders)
    Vilas Pawar       raises capital orders      (cannot see bought-out orders)
    Sachin Rashinkar  HOD, first approval
    Devang Jhaveri    Plant Head, posts the order
"""
import json
import time
import urllib.error
import urllib.request

URL = 'https://linked-staging2.odoo.com/jsonrpc'
DB = 'linkederp-stagingdm-36147382'
LOGIN = 'mahesh@shubhada.demo'
PWD = 'Shubhada@2026'
CTX = {'context': {'allowed_company_ids': [4], 'company_id': 4}}
_id = [0]

MAHESH, VILAS, SACHIN, DEVANG = 179, 180, 178, 177

# code -> (rate paid last month, rate quoted on the live order)
HISTORY = {
    '26104501': 13.50,
    '26202361': 20.00,
    '26202371': 2.10,
    '26106731': 2.40,
    '26102331': 165.00,
}
HISTORIC_QTY = 100.0


def rpc(service, method, args, timeout=600):
    _id[0] += 1
    body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': _id[0],
                       'params': {'service': service, 'method': method,
                                  'args': args}}).encode()
    j = None
    for attempt in range(20):
        req = urllib.request.Request(URL, body, {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code != 503 or attempt == 19:
                raise
            if attempt == 0:
                print('      instance restarting (503) - waiting...')
            time.sleep(30)
    if 'error' in j:
        d = j['error'].get('data') or {}
        raise RuntimeError((d.get('message') or j['error'].get('message', ''))[:1500])
    return j['result']


UID = rpc('common', 'authenticate', [DB, LOGIN, PWD, {}])
if not UID:
    raise SystemExit('login failed for ' + LOGIN)
print('logged in as %s (uid %s)\n' % (LOGIN, UID))


def c(model, method, *args, **kw):
    kw = dict(CTX, **kw)
    return rpc('object', 'execute_kw', [DB, UID, PWD, model, method, list(args), kw])


def one(model, domain, fields=None):
    res = c(model, 'search_read', domain, fields or ['id'], limit=1)
    return res[0] if res else None


def create(model, vals):
    res = c(model, 'create', [vals])
    return res[0] if isinstance(res, list) else res


def group(xmlid):
    r = one('ir.model.data',
            [('module', '=', 'shubhada_purchase_galaxy'), ('name', '=', xmlid)],
            ['res_id'])
    if not r:
        raise SystemExit('group %s not found - is version 19.0.1.0.3 installed?' % xmlid)
    return r['res_id']


# --------------------------------------------------------------- 1. the cast
print('[1/3] group membership')
CAST = [
    (MAHESH, 'group_buyer_boughtout', 'Mahesh Joshi -> bought-out buyer'),
    (VILAS, 'group_buyer_capital', 'Vilas Pawar -> capital buyer'),
    (SACHIN, 'group_po_hod', 'Sachin Rashinkar -> HOD (first approval)'),
    (DEVANG, 'group_po_poster', 'Devang Jhaveri -> Plant Head (posts)'),
]
for uid, xmlid, label in CAST:
    gid = group(xmlid)
    c('res.users', 'write', [uid], {'group_ids': [(4, gid)]})
    print('      %s' % label)


# ------------------------------------------------------- 2. the historic order
print('[2/3] last month\'s order (for Last Purchased Rate)')
vendor = one('res.partner', [('name', '=', 'S.S TRADERS')], ['id'])
if not vendor:
    raise SystemExit('S.S TRADERS not found - run SEED-GALAXY-PO.py first.')
series = one('shubhada.po.series', [('code', '=', 'PC01')], ['id'])
division = one('shubhada.division', [('code', '=', 'NSK')], ['id'])

products = {}
for code in HISTORY:
    p = one('product.product', [('default_code', '=', code)], ['id', 'name'])
    if not p:
        raise SystemExit('product %s missing - run SEED-GALAXY-PO.py first.' % code)
    products[code] = p

historic = one('purchase.order',
               [('partner_id', '=', vendor['id']),
                ('x_approval_state', '=', 'posted'),
                ('x_series_id', '=', series['id'])],
               ['id', 'name', 'x_galaxy_number'])
if historic:
    print('      already there: %s' % historic['x_galaxy_number'])
else:
    hid = create('purchase.order', {
        'partner_id': vendor['id'],
        'date_order': '2026-07-17 10:20:00',
        'x_series_id': series['id'],
        'x_division_id': division['id'],
        'x_for_division_id': division['id'],
        'x_our_reference': 'Store Dept.',
        'x_payment_mode': 'credit',
        'order_line': [(0, 0, {
            'product_id': products[code]['id'],
            'name': products[code]['name'],
            'product_qty': HISTORIC_QTY,
            'price_unit': old,
            'date_planned': '2026-07-24 09:00:00',
        }) for code, old in HISTORY.items()],
    })
    # It was raised by Vilas, so Mahesh is allowed to approve it - the module
    # refuses to let anyone clear their own order.
    c('purchase.order', 'write', [hid], {'x_created_uid': VILAS})
    c('purchase.order', 'action_galaxy_submit', [hid])
    c('purchase.order', 'action_galaxy_approve_hod', [hid])
    c('purchase.order', 'action_galaxy_post', [hid])
    historic = one('purchase.order', [('id', '=', hid)],
                   ['id', 'name', 'x_galaxy_number', 'state'])
    print('      posted as %s' % historic['x_galaxy_number'])


# ------------------------------- 3. a capital order + schedules on every line
print('[3/3] capital order and delivery schedules')
cap_series = one('shubhada.po.series', [('code', '=', 'PC03')], ['id'])
capital = one('purchase.order', [('x_series_id', '=', cap_series['id'])],
              ['id', 'name', 'x_galaxy_number'])
if capital:
    print('      capital order already there: %s'
          % (capital['x_galaxy_number'] or capital['name']))
else:
    compressor = one('product.product', [('default_code', '=', 'CAP-COMP-75')], ['id'])
    if not compressor:
        compressor = {'id': create('product.product', {
            'name': 'Screw Air Compressor 75 HP',
            'default_code': 'CAP-COMP-75',
            'type': 'consu',
            'is_storable': True,
            'purchase_ok': True,
            'sale_ok': False,
            'standard_price': 1450000.0,
        })}
    cid = create('purchase.order', {
        'partner_id': vendor['id'],
        'date_order': '2026-08-19 11:00:00',
        'x_series_id': cap_series['id'],
        'x_division_id': division['id'],
        'x_for_division_id': division['id'],
        'x_our_reference': 'Engineering',
        'x_payment_mode': 'advance',
        'order_line': [(0, 0, {
            'product_id': compressor['id'],
            'name': 'Screw Air Compressor 75 HP',
            'product_qty': 1.0,
            'price_unit': 1450000.0,
            'date_planned': '2026-09-30 09:00:00',
        })],
    })
    c('purchase.order', 'write', [cid], {'x_created_uid': VILAS})
    c('purchase.order', 'action_galaxy_submit', [cid])
    c('purchase.order', 'action_galaxy_approve_hod', [cid])
    c('purchase.order', 'action_galaxy_post', [cid])
    capital = one('purchase.order', [('id', '=', cid)], ['id', 'name', 'x_galaxy_number'])
    print('      capital order posted as %s' % capital['x_galaxy_number'])

draft = one('purchase.order',
            [('partner_id', '=', vendor['id']), ('x_approval_state', '=', 'draft')],
            ['id', 'name'])
if not draft:
    raise SystemExit('No draft order found - run SEED-GALAXY-PO.py first.')

added = 0
for line in c('purchase.order.line', 'search_read',
              [('order_id', '=', draft['id'])],
              ['id', 'product_qty', 'x_schedule_ids']):
    if line['x_schedule_ids']:
        continue
    create('shubhada.po.schedule', {
        'line_id': line['id'],
        'required_date': '2026-08-28',
        'required_qty': line['product_qty'],
        'state': 'confirmed',
    })
    added += 1
print('      %d schedule rows added' % added)


# ------------------------------------------------------------------- report
rows = c('purchase.order.line', 'search_read', [('order_id', '=', draft['id'])],
         ['name', 'product_qty', 'price_unit', 'x_last_purchase_rate'])
print('\n' + '=' * 72)
print('  READY TO RECORD')
print('=' * 72)
print('  %-42s %9s %9s' % ('ITEM', 'LAST', 'NOW'))
for r in rows:
    print('  %-42s %9.2f %9.2f'
          % (r['name'][:42], r['x_last_purchase_rate'], r['price_unit']))
print('-' * 72)
print('  Live draft      %s   (raise / submit as Mahesh)' % draft['name'])
print('  Approve as      sachin@shubhada.demo   then   devang@shubhada.demo')
print('  History order   %s' % historic['x_galaxy_number'])
print('  Capital order   %s   (Mahesh must NOT be able to see this one)'
      % capital['x_galaxy_number'])
print('=' * 72)
print('Tell Claude everything printed between the lines above.')
