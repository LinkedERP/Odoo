{
    'name': 'Shubhada Purchase (Galaxy parity)',
    'version': '19.0.1.0.5',
    'summary': 'Series-segmented Purchase Orders with maker-checker approval, '
               'Galaxy-style document numbering, amendments and delivery schedules.',
    'description': """
Shubhada Purchase — Galaxy parity
=================================

Reproduces the purchase-order controls Shubhada runs today in Galaxy, on Odoo 19:

* **Series / segment** — Bought-out, Subcontracting, Local Capital, Open Order,
  Subcontracting with BOM, Service. Each series carries its own document code and
  its own running serial, and can be restricted to its own buyer group.
* **Division and location** — every order is raised for a division; reports and
  permissions follow it.
* **Galaxy document numbering** — ``SHN27PO04203`` = company + division + financial
  year + document code + series serial. **Assigned on approval, not on save.**
* **Maker-checker workflow** — draft -> submitted -> HOD approved -> posted, with
  Created by / Modified by / Posted by stamped automatically.
* **Amendments** — amendment number and date, with the order returning to the
  approval chain when amended.
* **Per-line delivery schedule** — required date, required / received / rejected
  quantity, short-closed and cancelled quantity, supplier confirmation reference.
* **Last purchased rate** shown on the line at entry time.
* **Document reference** — the PR (or other source document) each order answers.

Built for the Shubhada Polymers evaluation.
""",
    'category': 'Inventory/Purchase',
    'author': 'LinkedERP',
    'website': 'https://linkederp.com',
    'license': 'LGPL-3',
    'depends': ['purchase', 'stock'],
    'data': [
        'security/purchase_galaxy_security.xml',
        'security/ir.model.access.csv',
        'data/series_data.xml',
        'data/amendment_sequence.xml',
        'views/masters_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_amendment_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
