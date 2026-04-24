import os
from odoo import http
from odoo.http import request

class CustomLlmsTxtController(http.Controller):
    @http.route('/llms.txt', type='http', auth='public', website=True)
    def custom_llms_txt(self, **kwargs):
        custom_path = '/opt/custom_llms/llms.txt'  # Ganti path ini jika perlu
        if not os.path.exists(custom_path):
            return request.not_found()
        try:
            with open(custom_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return request.not_found()
        return request.make_response(content, [
            ('Content-Type', 'text/plain; charset=utf-8'),
        ])

