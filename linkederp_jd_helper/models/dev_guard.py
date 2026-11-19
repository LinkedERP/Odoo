# -*- coding: utf-8 -*-
"""Odoo.sh copies Dev to a fresh database now and then. The copy is "neutralized": every scheduled job is switched off
and the mail servers are removed. Odoo's daily autovacuum job is the one job left on, so it switches ours back on and
puts back the server that stops Dev from emailing anyone. It only acts on neutralized copies, never on production.
"""
from odoo import api, models

BLOCK = "BLOCK - no emails from Dev"


class LinkederpDevGuard(models.AbstractModel):
    _inherit = "linkederp.jd.helper"

    @api.autovacuum
    def _gc_dev_copy_repair(self):
        if not self.env["ir.config_parameter"].sudo().get_param("database.is_neutralized"):
            return
        Server = self.env["ir.mail_server"].sudo().with_context(active_test=False)
        if not Server.search([("name", "=", BLOCK)]):
            Server.create({"name": BLOCK, "smtp_host": "127.0.0.1", "smtp_port": 1, "sequence": 1, "smtp_encryption": "none"})
        ours = self.env["ir.model.data"].sudo().search([("module", "=", "linkederp_jd_helper"), ("model", "=", "ir.cron")])
        crons = self.env["ir.cron"].sudo().with_context(active_test=False).browse(ours.mapped("res_id"))
        lease = self.env["ir.cron"].sudo().with_context(active_test=False).search([("name", "=", "Ruby: lease and document reminders")])
        (crons | lease).filtered(lambda c: not c.active).write({"active": True})
