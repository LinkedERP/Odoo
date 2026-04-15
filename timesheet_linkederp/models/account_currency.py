from odoo import models, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.onchange('project_id')
    def _onchange_project_set_currency_and_company(self):
        """
        When a project is selected, set invoice company and currency
        from project's company settings.
        Only works in draft invoices to avoid validation errors.
        """
        for rec in self:
            if rec.state == 'draft' and rec.project_id and rec.project_id.company_id:
                # Change company only if allowed
                if rec.company_id != rec.project_id.company_id:
                    rec.company_id = rec.project_id.company_id

                # Always set currency from project's company
                rec.currency_id = rec.project_id.company_id.currency_id
