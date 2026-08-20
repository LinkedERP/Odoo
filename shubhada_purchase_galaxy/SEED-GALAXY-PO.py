"""Install shubhada_purchase_galaxy and seed the purchase order from Mahesh's screen.

Run it straight after pushing to StagingDM - it waits for the build itself:

    python SEED-GALAXY-PO.py

Authenticates as the demo admin persona with the plain password - no API key.
Only creates what is missing, and leaves the order in DRAFT so the approval
chain can be shown live on camera.
"""
import json
import time
import urllib.error
import urllib.request

URL = 'https://linked-staging2.odoo.com/jsonrpc'
DB = 'linkederp-stagingdm-36147382'
LOGIN = 'mahesh@shubhada.demo'
PWD = 'Shubhada@2026'

MODULE = 'shubhada_purchase_galaxy'
# Keep in step with __manifest__.py. The script refuses to install until Odoo.sh
# has actually published this version - see wait_for_build().
EXPECT_VERSION = '19.0.1.0.3'

CTX = {'context': {'allowed_company_ids': [4], 'company_id': 4}}
_id = [0]
REPORT = []


def rpc(service, method, args, timeout=600):
    """One JSON-RPC call, waiting out an Odoo.sh restart if the instance is down."""
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
                print('      instance is restarting (503) - waiting...')
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


def wait_for_build(minutes=12):
    """Block until the running instance actually serves EXPECT_VERSION.

    An Odoo.sh staging rebuild keeps the PREVIOUS build live until the new one is
    ready, so a fresh push is not visible straight away and there is no 503 to
    catch - the old code just quietly answers. For a module that is not installed,
    ir.module.module.installed_version reports the version in the manifest ON DISK,
    which is how old code can be told apart from new.
    """
    deadline = time.time() + minutes * 60
    said = None
    while True:
        try:
            c('ir.module.module', 'update_list')
        except RuntimeError as e:
            print('      update_list failed: %s' % str(e)[:160])

        rec = one('ir.module.module', [('name', '=', MODULE)],
                  ['state', 'id', 'installed_version', 'latest_version'])
        if rec:
            on_disk = (rec['latest_version'] if rec['state'] == 'installed'
                       else rec['installed_version'])
            if on_disk == EXPECT_VERSION:
                return rec
            msg = 'serving %s, waiting for %s' % (on_disk or '?', EXPECT_VERSION)
        else:
            msg = 'not in the apps list yet'

        if msg != said:
            print('      %s ...' % msg)
            said = msg
        if time.time() > deadline:
            raise SystemExit(
                '\nGave up after %d minutes waiting for version %s.\n'
                '  -> The Odoo.sh build for StagingDM has not published it.\n'
                '  -> Check the StagingDM build log on the Odoo.sh dashboard.\n'
                '  -> Nothing has been changed.' % (minutes, EXPECT_VERSION))
        time.sleep(30)


# ------------------------------------------------------------ 1. install module
print('[1/4] module')
mod = wait_for_build()
print('      version %s is live on the instance' % EXPECT_VERSION)
if mod['state'] == 'installed':
    print('      already installed - upgrading to this version...')
    c('ir.module.module', 'button_immediate_upgrade', [mod['id']])
    print('      upgraded')
else:
    print('      state is %s - installing...' % mod['state'])
    c('ir.module.module', 'button_immediate_install', [mod['id']])
    print('      installed')
REPORT.append(('MODULE', '%s %s' % (MODULE, EXPECT_VERSION)))


# ------------------------------------------------------------------ 2. vendor
print('[2/4] vendor')
VENDOR_NAME = 'S.S TRADERS'
vendor = one('res.partner', [('name', '=', VENDOR_NAME)], ['id'])
if vendor:
    vendor_id = vendor['id']
    print('      exists: %s' % VENDOR_NAME)
else:
    vendor_id = create('res.partner', {
        'name': VENDOR_NAME,
        'ref': '2190392',
        'street': 'SHOP No.17-18, Flora Shopping Center',
        'street2': 'Near INDOLINE Furniture, MIDC AMBAD',
        'city': 'Nashik',
        'zip': '422010',
        'is_company': True,
        'supplier_rank': 1,
    })
    print('      created: %s' % VENDOR_NAME)
REPORT.append(('VENDOR', '%s (ref 2190392)' % VENDOR_NAME))


# ---------------------------------------------------------------- 3. products
print('[3/4] items')
ITEMS = [
    ('26104501', 'KNITTED HAND SLEEVES', 150.0, 14.00),
    ('26202361', 'MASKING TAPE', 90.0, 21.00),
    ('26202371', 'HEAD CAP', 200.0, 2.00),
    ('26106731', 'NOSE MASK- PATTI(STRIP)-GREEN/BLUE -(FOR IM)', 200.0, 2.50),
    ('26102331', 'COTTON ROLL', 10.0, 170.00),
]

uom = (one('uom.uom', [('name', '=', 'Units')], ['id'])
       or c('uom.uom', 'search_read', [], ['id'], limit=1)[0])
UOM_ID = uom['id']

product_ids = {}
made = 0
for code, name, _qty, rate in ITEMS:
    prod = one('product.product', [('default_code', '=', code)], ['id'])
    if prod:
        product_ids[code] = prod['id']
        continue
    product_ids[code] = create('product.product', {
        'name': name,
        'default_code': code,
        'type': 'consu',
        'is_storable': True,
        'purchase_ok': True,
        'sale_ok': False,
        'standard_price': rate,
        'uom_id': UOM_ID,
    })
    made += 1
print('      %d items ready (%d newly created)' % (len(product_ids), made))
REPORT.append(('ITEMS', '%d items, 26104501 ... 26102331' % len(product_ids)))


# ------------------------------------------------------------ 4. purchase order
print('[4/4] purchase order')
series = one('shubhada.po.series', [('code', '=', 'PC01')],
             ['id', 'name', 'next_serial', 'document_code'])
division = one('shubhada.division', [('code', '=', 'NSK')],
               ['id', 'company_letters', 'number_letter'])
if not series or not division:
    raise SystemExit('Series PC01 or division NSK missing - module data did not load.')

existing = one('purchase.order',
               [('partner_id', '=', vendor_id),
                ('x_series_id', '=', series['id']),
                ('x_approval_state', '=', 'draft')],
               ['id', 'name'])
if existing:
    po_id = existing['id']
    print('      draft already staged: %s' % existing['name'])
else:
    lines = [(0, 0, {
        'product_id': product_ids[code],
        'name': name,
        'product_qty': qty,
        'price_unit': rate,
        'date_planned': '2026-08-28 09:00:00',
    }) for code, name, qty, rate in ITEMS]

    po_id = create('purchase.order', {
        'partner_id': vendor_id,
        'date_order': '2026-08-21 09:56:00',
        'x_series_id': series['id'],
        'x_division_id': division['id'],
        'x_for_division_id': division['id'],
        'x_wef_date': '2026-08-21',
        'x_validity_date': '2027-03-31',
        'x_our_reference': 'Store Dept.',
        'x_payment_mode': 'credit',
        'order_line': lines,
        'x_doc_ref_ids': [(0, 0, {
            'document_type': 'PR',
            'document_number': 'SHN27A001269',
            'amendment_number': 0,
            'department_code': 'STORES',
            'department_name': 'STORES DEPARTMENT',
            'quantity': 150.0,
        })],
    })
    print('      created draft')

    first_line = one('purchase.order.line', [('order_id', '=', po_id)],
                     ['id', 'product_qty'])
    if first_line:
        create('shubhada.po.schedule', {
            'line_id': first_line['id'],
            'required_date': '2026-08-28',
            'required_qty': first_line['product_qty'],
            'state': 'confirmed',
        })

po = one('purchase.order', [('id', '=', po_id)],
         ['name', 'amount_untaxed', 'amount_total', 'x_approval_state'])
next_number = '{co}{d}27{doc}{s:05d}'.format(
    co=division['company_letters'], d=division['number_letter'],
    doc=series['document_code'], s=series['next_serial'])

REPORT.append(('ORDER', '%s  (draft, %d lines, basic Rs %.2f, total Rs %.2f)'
               % (po['name'], len(ITEMS), po['amount_untaxed'], po['amount_total'])))
REPORT.append(('SERIES', series['name']))
REPORT.append(('ON POST', 'the number will read  %s' % next_number))

print('\n' + '=' * 68)
print('  READY TO RECORD')
print('=' * 68)
for k, v in REPORT:
    print('  %-8s %s' % (k, v))
print('=' * 68)
print('Open:  Purchase (Shubhada) -> Purchase Orders -> %s' % po['name'])
print('Then:  Submit for Approval  ->  HOD Approve  ->  Post')
print('Tell Claude everything printed between the lines above.')
