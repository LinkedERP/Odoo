from odoo import models, fields, tools

class DuplicatePartnerEmail(models.Model):
    _name = "duplicate.partner.email"
    _description = "Duplicate Partner Emails"
    _auto = False

    email = fields.Char(string="Email")
    duplicate_count = fields.Integer(string="Duplicate Count")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "duplicate_partner_email")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW duplicate_partner_email AS (
                SELECT
                    MIN(id) AS id,
                    email,
                    COUNT(*) AS duplicate_count
                FROM res_partner
                WHERE email IS NOT NULL
                GROUP BY email
                HAVING COUNT(*) > 1
            )
        """)
