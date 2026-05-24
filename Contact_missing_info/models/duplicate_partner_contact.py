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

                SELECT
                    abs(hashtext(duplicate_type || '|' || value))::bigint AS id,
                    duplicate_type,
                    value,
                    duplicate_count
                FROM (

                    -- Duplicate Emails
                    SELECT
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
                        'phone' AS duplicate_type,
                        phone AS value,
                        COUNT(*) AS duplicate_count
                    FROM res_partner
                    WHERE phone IS NOT NULL
                    GROUP BY phone
                    HAVING COUNT(*) > 1

                ) sub
            )
        """)

    def action_open_partners(self):
        """Return an action that opens res.partner records matching this view row's value.

        Must be called from a form/view with a single record selected.
        """
        self.ensure_one()
        if not self.value:
            return {
                'type': 'ir.actions.act_window_close'
            }
        if self.duplicate_type == 'email':
            domain = [('email', '=', self.value)]
        else:
            domain = [('phone', '=', self.value)]
        return {
            'name': 'Partners matching %s' % (self.value,),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'tree,form',
            'domain': domain,
            'context': {'search_default_has_email': 1} if self.duplicate_type == 'email' else {},
        }
