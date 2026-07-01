{
    'name': 'Timesheet LinkedERP modifier',
    'version': '1.1.1',
    'summary': 'Project and User company should be same while filling Timesheet',
    'description': """
Timesheet LinkedERP Modifier
============================

Adjusts timesheet (account.analytic.line) behaviour so logged time stays
consistent with company boundaries and open sales orders:

* Company guard: a timesheet can only be logged on a project of the current company.
* Project selector hides projects whose re-invoice sale order is completed.
* SO line selector excludes lines of completed sale orders, scoped per customer.
* Helpdesk -> Task time roll-up (A05): one line may link to both a task and a
  ticket, counted once at project level, surfaced at task and ticket level.
""",
    'category': 'Services/Timesheets',
    'author': 'JV',
    'website': 'https://Linkederp.com',
    'license': 'AGPL-3',
    'depends': ['account', 'hr_timesheet', 'sale_timesheet','helpdesk_sale_timesheet'],
    'data': [
    'views/timesheet_views.xml'
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}