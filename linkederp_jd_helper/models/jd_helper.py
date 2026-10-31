# -*- coding: utf-8 -*-
"""Drafts a LinkedERP JD for a hiring request with VectorMind (BusinessGPT).

The hiring request model (x_hiring_request) is a Studio-style model, so it is used through env at run time.
VectorMind route proven 2026-09-10: a machine client only answers on external-threads + external-messages
with stream:true; their gateway can hang up at ~100 s, after which the answer lands on the thread
labelled anything but 'User'.
"""
import base64
import io
import json
import logging
import re
import time
import zipfile
from html import escape

import requests

from odoo import api, models

try:  # name differs across versions
    from odoo.tools.pdf import PdfFileReader
except ImportError:  # pragma: no cover
    from pypdf import PdfReader as PdfFileReader

_logger = logging.getLogger(__name__)

VM = "https://linkederp.vectormind.chat"
DEFAULT_BOT = "0b21c99f-e7f0-491f-8565-d2998683da79"  # gpt-5.5 bot on the LinkedERP tenant
P = "linkederp_jd_helper."

ABOUT = ("LinkedERP is a NetSuite and Odoo implementation partner serving clients across South Africa, India and Indonesia. "
         "We take growing and enterprise businesses through the full ERP journey: consulting, solution design, implementation "
         "and post-go-live support, with deep expertise in manufacturing, supply chain and cloud-first transformation.")

PROMPT = """You write job descriptions for LinkedERP. {about}

Write a complete JD for the role below, in the same depth and style as the EXAMPLE.
Rules: plain, simple English; role names only, never people's names; no em dashes; Indian context (Bengaluru office) unless the input says otherwise;
levels are Junior / Proficient / Senior for NetSuite, Odoo, DSI and AI roles, and BDR / Assistant Manager / Country Sales Manager for sales;
7 to 10 key responsibilities, each with a short area name and 2 to 3 sentences; 4 to 6 required skills; 2 to 4 preferred; 3 to 4 qualities; 2 to 3 offer lines.
If the input is a sample JD from elsewhere, keep its substance but rewrite it fully into our format and voice.

Return ONLY a JSON object with exactly these keys:
{{"title": str, "subtitle": "Area  ·  Function", "meta": [["Location", str], ["Employment Type", str], ["Experience Required", str], ["Reports To", str]],
 "overview": str, "responsibilities": [[area, text], ...], "skills": [str or [lead, text]], "preferred": [str], "qualities": [str], "offer": [str]}}

EXAMPLE (one of our library JDs):
{example}

ROLE INPUT:
{role}
"""


def _items(items):
    out = []
    for i in items or []:
        if isinstance(i, (list, tuple)) and len(i) == 2:
            out.append("<li><b>%s:</b> %s</li>" % (escape(str(i[0])), escape(str(i[1]))))
        else:
            out.append("<li>%s</li>" % escape(str(i)))
    return "<ul>" + "".join(out) + "</ul>"


def jd_html(r):
    """Same layout as the JD library jobs (Documents\\LinkedERP-JDs, step9 in Odoo-HR-Office-Dev)."""
    meta = "".join("<li><b>%s:</b> %s</li>" % (escape(str(k)), escape(str(v))) for k, v in r.get("meta", []))
    parts = ["<p><i>%s</i></p><ul>%s</ul>" % (escape(r.get("subtitle", "")), meta),
             "<h3>Role overview</h3>", "<p>%s</p>" % escape(r.get("overview", ""))]
    for h, key in [("Key responsibilities", "responsibilities"), ("Required skills and experience", "skills"),
                   ("Preferred qualifications", "preferred"), ("Personal qualities", "qualities"), ("What we offer", "offer")]:
        parts += ["<h3>%s</h3>" % h, _items(r.get(key))]
    return "".join(parts)


def parse_json(text):
    t = str(text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    return json.loads(t[t.find("{"):t.rfind("}") + 1])


class LinkederpJdHelper(models.AbstractModel):
    _name = "linkederp.jd.helper"
    _description = "LinkedERP JD Helper (VectorMind)"

    # ---------- called by the "Draft JD with AI" button ----------
    @api.model
    def request_draft(self, record_ids):
        recs = self.env["x_hiring_request"].browse(record_ids)
        recs.write({"x_ai_status": "requested", "x_ai_note": False})
        self.env.ref("linkederp_jd_helper.ir_cron_draft_jd")._trigger()
        return True

    # ---------- scheduled job ----------
    @api.model
    def _cron_draft_jds(self):
        for rec in self.env["x_hiring_request"].search([("x_ai_status", "=", "requested")], limit=10):
            try:
                self._draft(rec)
            except Exception as e:  # one bad request must not stop the rest
                _logger.exception("JD helper failed on hiring request %s", rec.id)
                rec.write({"x_ai_status": "failed", "x_ai_note": ("Could not draft: %s" % e)[:180]})
            self.env.cr.commit()

    def _draft(self, rec):
        sample = self._file_text(rec)
        parts = [rec.x_name and "Job title asked: %s" % rec.x_name,
                 rec.x_new_role_brief and "Description from the hiring manager: %s" % rec.x_new_role_brief,
                 sample and "Sample JD they attached:\n%s" % sample[:12000]]
        role = "\n".join(p for p in parts if p)
        if not role.strip():
            raise ValueError("nothing to work from, add a description or attach a sample JD")
        jd = parse_json(self._ask(PROMPT.format(about=ABOUT, example=self._example(), role=role)))
        exp = dict((k, v) for k, v in jd.get("meta", [])).get("Experience Required", "")
        vals = {"x_about_role": jd_html(jd), "x_ai_status": "done", "x_ai_note": False}
        if not rec.x_name:
            vals["x_name"] = jd.get("title")
        if exp and not rec.x_experience:
            vals["x_experience"] = exp
        rec.write(vals)
        rec.message_post(body="JD drafted by the AI helper (VectorMind). Please check it before submitting.")

    def _example(self):
        job = self.env["hr.job"].search([("x_jd_library", "=", True), ("name", "=", "Project Manager")], limit=1)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(job.description or "")))[:6000]

    def _file_text(self, rec):
        if not rec.x_jd_file:
            return ""
        raw = base64.b64decode(rec.x_jd_file)
        name = (rec.x_jd_filename or "").lower()
        if name.endswith(".pdf"):
            reader = PdfFileReader(io.BytesIO(raw), strict=False)
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        if name.endswith(".docx"):
            xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode("utf-8", "ignore")
            xml = re.sub(r"</w:p>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml)
        return raw.decode("utf-8", "ignore")

    # ---------- VectorMind ----------
    def _ask(self, content):
        icp = self.env["ir.config_parameter"].sudo()
        cid, secret = icp.get_param(P + "vm_client_id"), icp.get_param(P + "vm_client_secret")
        if not (cid and secret):
            raise ValueError("VectorMind is not set up (System Parameters linkederp_jd_helper.vm_client_id / vm_client_secret)")
        bot = icp.get_param(P + "vm_bot_id") or DEFAULT_BOT
        tok = requests.post(VM + "/security/connect/token", timeout=30, data={
            "grant_type": "client_credentials", "client_id": cid, "client_secret": secret, "scope": "api"})
        tok.raise_for_status()
        h = {"Authorization": "Bearer " + tok.json()["access_token"]}
        api_ = VM + "/_apis/server/api"
        thread = requests.post(api_ + "/external-threads", headers=h, timeout=30,
                               json={"name": "hr-office", "userId": "hr-office", "botId": bot})
        thread.raise_for_status()
        tid = thread.json()["id"]
        try:
            r = requests.post(api_ + "/external-messages", headers=h, timeout=150, json={
                "threadId": tid, "content": content, "contentType": "PlainText", "messageType": "User", "botId": bot,
                "searchWeb": False, "externalUserId": "hr-office", "stream": True})
            r.raise_for_status()
            return r.json().get("content", "")
        except (requests.Timeout, requests.HTTPError):
            for _ in range(20):  # up to 5 minutes on the thread
                time.sleep(15)
                lst = requests.get(api_ + "/external-messages/thread/%s" % tid, headers=h, timeout=30)
                if not lst.ok:
                    continue
                data = lst.json()
                answers = [m for m in (data if isinstance(data, list) else data.get("items", [])) if m.get("messageType") != "User"]
                if answers and re.search(r"[}\]`.!?]\s*$", str(answers[-1].get("content", "")).strip()):
                    return answers[-1]["content"]
            raise
