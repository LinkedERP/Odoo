from odoo import models, fields, tools

class DuplicatePartnerContact(models.Model):
    _name = "duplicate.partner.contact"
    _description = "Duplicate Partner Contacts (Email / Phone)"
    _auto = False

    duplicate_type = fields.Selection(
        [
            ("email", "Email"),
            ("phone", "Phone"),
        ],
        string="Duplicate Type",
        readonly=True,
    )
    value = fields.Char(string="Email / Phone", readonly=True)
    duplicate_count = fields.Integer(string="Duplicate Count", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "duplicate_partner_contact")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW duplicate_partner_contact AS (

                -- Duplicate Emails
                SELECT
                    MIN(id) AS id,
                    'email' AS duplicate_type,
                    email AS value,
                    COUNT(*) AS duplicate_count
                FROM res_partner
                WHERE email IS NOT NULL
                GROUP BY email
                HAVING COUNT(*) > 1

                UNION ALL

                -- Duplicate Phones
                SELECT
                    MIN(id) AS id,
                    'phone' AS duplicate_type,
                    phone AS value,
                    COUNT(*) AS duplicate_count
                FROM res_partner
                WHERE phone IS NOT NULL
                GROUP BY phone
                HAVING COUNT(*) > 1
            )
        """)
