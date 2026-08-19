import os
from odoo import http
from odoo.http import request

_HTML_PATH = os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'dashboard.html')


class ShubhadaDashboard(http.Controller):
    @http.route('/shubhada/dashboard', type='http', auth='user', website=False)
    def dashboard(self, **kw):
        with open(_HTML_PATH, encoding='utf-8') as f:
            html = f.read()
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])
