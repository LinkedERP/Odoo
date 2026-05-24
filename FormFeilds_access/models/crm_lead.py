from odoo import models

class CrmLead(models.Model):
    _inherit = "crm.lead"

    def create(self, vals_list):
        return super(
            CrmLead,
            self.with_context(from_crm=True)
        ).create(vals_list)

    def write(self, vals):
        return super(
            CrmLead,
            self.with_context(from_crm=True)
        ).write(vals)

    def _create_customer(self):
        return super(
            CrmLead,
            self.with_context(from_crm=True)
        )._create_customer()