# -*- coding: utf-8 -*-
"""Microsoft 365 accounts for new joiners, through the "HR Office (Odoo)" app in Entra.

Keys live in System Parameters: hr_office.ms_tenant_id / ms_client_id / ms_client_secret.
Optional hr_office.ms_license_sku (a skuId): when empty, the account is made without a licence.
"""
import base64
import json
import secrets
import string

import requests

from odoo import api, models
from odoo.exceptions import UserError

GRAPH = "https://graph.microsoft.com/v1.0"


class LinkederpMicrosoft(models.AbstractModel):
    _inherit = "linkederp.jd.helper"

    def _ms_param(self, key):
        return self.env["ir.config_parameter"].sudo().get_param("hr_office." + key)

    def _ms_token(self):
        tenant, client, secret = (self._ms_param(k) for k in ("ms_tenant_id", "ms_client_id", "ms_client_secret"))
        if not (tenant and client and secret):
            raise UserError("The Microsoft keys are missing in System Parameters (hr_office.ms_...).")
        r = requests.post("https://login.microsoftonline.com/%s/oauth2/v2.0/token" % tenant.strip(), timeout=30, data={
            "grant_type": "client_credentials", "client_id": client.strip(), "client_secret": secret.strip(),
            "scope": "https://graph.microsoft.com/.default"})
        if not r.ok:
            raise UserError("Microsoft refused the keys: %s" % r.json().get("error_description", r.text)[:300])
        return r.json()["access_token"]

    def _ms(self, method, path, token, **kw):
        r = requests.request(method, GRAPH + path, headers={"Authorization": "Bearer " + token}, timeout=30, **kw)
        if r.status_code == 404:
            return None
        if not r.ok:
            raise UserError("Microsoft said no (%s): %s" % (r.status_code, r.json().get("error", {}).get("message", r.text)[:300]))
        return r.json() if r.content else {}

    @api.model
    def ms_check(self, email="priya@linkederp.com"):
        """Read-only proof: keys work, which rights the app has, domains, licences, whether an email is free."""
        token = self._ms_token()
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        org = self._ms("GET", "/organization", token)["value"][0]
        skus = self._ms("GET", "/subscribedSkus", token)["value"]
        return {
            "org": org["displayName"], "rights": sorted(claims.get("roles", [])),
            "domains": [d["name"] for d in org["verifiedDomains"]],
            "licences": ["%s: %s used of %s (%s)" % (s["skuPartNumber"], s["consumedUnits"], s["prepaidUnits"]["enabled"], s["skuId"])
                         for s in skus],
            "email_taken": bool(self._ms("GET", "/users/%s" % email, token)),
        }

    def _ms_free_email(self, token, first, last):
        domain = self._ms_param("ms_domain") or "linkederp.com"
        clean = lambda s: "".join(c for c in (s or "").lower() if c.isalnum())
        for nick in (clean(first), clean(first) + clean(last)[:1], clean(first) + clean(last)):
            if nick and not self._ms("GET", "/users/%s@%s" % (nick, domain), token):
                return nick, "%s@%s" % (nick, domain)
        raise UserError("No free work email for %s %s. Please create the Microsoft account by hand." % (first, last))

    @api.model
    def ms_create_user(self, name, country="IN"):
        """Create the Microsoft account. Returns (email, temporary password). The password is never emailed."""
        token = self._ms_token()
        first, _, last = name.strip().partition(" ")
        nick, email = self._ms_free_email(token, first, last.split(" ")[-1] if last else "")
        pwd = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10)) + "!7a"
        user = self._ms("POST", "/users", token, json={
            "accountEnabled": True, "displayName": name, "givenName": first, "surname": last or None,
            "mailNickname": nick, "userPrincipalName": email, "usageLocation": country,
            "passwordProfile": {"forceChangePasswordNextSignIn": True, "password": pwd}})
        sku = self._ms_param("ms_license_sku")
        if sku:
            self._ms("POST", "/users/%s/assignLicense" % user["id"], token,
                     json={"addLicenses": [{"skuId": sku, "disabledPlans": []}], "removeLicenses": []})
        return email, pwd

    @api.model
    def ms_delete_user(self, email):
        """Test clean-up: delete the account (Microsoft keeps it 30 days in the recycle bin)."""
        token = self._ms_token()
        return self._ms("DELETE", "/users/%s" % email, token) is not None
