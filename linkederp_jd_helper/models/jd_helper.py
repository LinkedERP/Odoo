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
from odoo.exceptions import UserError

try:  # name differs across versions
    from odoo.tools.pdf import PdfFileReader
except ImportError:  # pragma: no cover
    from pypdf import PdfReader as PdfFileReader

_logger = logging.getLogger(__name__)

VM = "https://linkederp.vectormind.chat"
DEFAULT_BOT = "0b21c99f-e7f0-491f-8565-d2998683da79"  # gpt-5.5 bot on the LinkedERP tenant
P = "linkederp_jd_helper."
SYNC_WAIT = 80  # seconds the user waits on screen; Odoo.sh stops web requests at about 120 s

ABOUT = ("LinkedERP is a NetSuite and Odoo implementation partner serving clients across South Africa, India and Indonesia. "
         "We take growing and enterprise businesses through the full ERP journey: consulting, solution design, implementation "
         "and post-go-live support, with deep expertise in manufacturing, supply chain and cloud-first transformation.")

# The house guide: the same rules the 23 library JDs were written with (Akshay's decisions, 31 Oct 2026).
# HR can replace it without code via System Parameter linkederp_jd_helper.style_guide.
STYLE_GUIDE = """LINKEDERP JD HOUSE GUIDE
Voice: plain, simple English (British spelling). Short, direct sentences. Role names only, never people's names. No em dashes. No buzzwords.

TITLE: the role, with the level after a dash when the role has levels, e.g. "Odoo Functional Consultant - Proficient".
SUBTITLE: "Area  ·  Track", e.g. "Delivery  ·  NetSuite", "Delivery  ·  Odoo", "Delivery  ·  DSI / Cloud Inventory", "Sales  ·  India",
"Marketing  ·  India, South Africa & Indonesia", "AI Platform  ·  Engineering", "Leadership  ·  India, South Africa & Indonesia".

LEVELS AND EXPERIENCE:
- NetSuite, Odoo, DSI and AI roles have three levels: Junior (0 to 2 Years), Proficient (3 to 6 Years), Senior (8+ Years; technical seniors 6+ Years).
- Sales has three levels: Business Development Representative (0 to 3 Years), Sales Assistant Manager (4 to 7 Years), Country Sales Manager (10+ Years).
- Leadership roles (Chief of Staff, AI Lead): 10+ Years. Project Manager: 8+ Years. Digital Marketing Specialist: 5 to 8 Years.

META (exactly these four lines, in this order):
- Location: "Bengaluru, India (Work from Office)"; AI roles "Bengaluru, India (Hybrid)".
- Employment Type: "Full-time, Permanent"; DSI roles "Full-time, Permanent (hybrid shifts or rotation, including US hours when needed)". Never "night shift".
- Experience Required: from the bands above unless the input says otherwise.
- Reports To: all NetSuite, Odoo and DSI delivery roles (functional and technical, every level) report to "Project Manager".
  AI engineers report to "AI Lead"; AI Lead reports to "Managing Director". BDR and Sales Assistant Manager report to "Country Sales Manager".
  Country Sales Manager, Digital Marketing Specialist and Project Manager report to "Chief of Staff". Chief of Staff reports to "Managing Director".

ROLE OVERVIEW: 2 to 4 sentences. First say what this role family does for our clients, then what changes at this level
("At Junior level you learn ...", "At Proficient level you own whole modules ...", "At Senior level you are the solution owner ...").

KEY RESPONSIBILITIES: 7 to 11 items. Each item = [short area name, 2 to 3 full sentences]. Be concrete to how LinkedERP works:
- We implement with our SILC method: Activate, Design, Build, CRP (conference room pilot), UAT, Go-live, Hypercare; each phase closes with a signed agreement.
- Requirements live in the functional and technical requirement lists (FRL and TRL); the plan lives in Smartsheet; time is booked in Odoo every day against the right deliverable.
- Indian clients need GST, TDS, e-invoicing (and e-way bills) set up correctly; we also serve South Africa, Indonesia and US (DSI) clients.
- Junior: learn the method and product, configure as directed, data loads, testing, documentation, first-level support.
- Proficient: run workshops, own modules, solution design (standard first), configuration, data migration, CRP and UAT, training, go-live and hypercare, mentor Juniors.
- Senior: solution ownership, design sign-off and quality, complex areas, escalations, pre-sales and estimates, mentoring and standards.
- Every delivery role ends with ["Plan and timesheets", "Keep your tasks current in the project plan, report progress and risks to the Project Manager, and book time in Odoo every day against the right deliverable."].
- Sales roles: targets, discovery, demos with consultants, proposals, CRM discipline, handover to delivery, weekly reporting.

REQUIRED SKILLS & EXPERIENCE: 4 to 6 items. Start with years and the core experience. Include one ["Tools", ...] item that mentions AI tools;
seniors may add ["Communication", ...].
PREFERRED QUALIFICATIONS: 2 to 3 items (certifications, industry background, degree).
PERSONAL QUALITIES: 3 to 4 items, for example "Owns outcomes end to end and closes loops without being chased.",
"Clear and honest communicator with clients and colleagues.", "Learns fast and is comfortable with changing priorities in a small team."
WHAT WE OFFER: 2 to 3 items. Always start with "A role with a fast-growing global NetSuite & Odoo partner spanning South Africa, India, and Indonesia."
For levelled roles add "A clear growth path through Junior, Proficient and Senior levels."

If the input is a sample JD from elsewhere: keep its substance (scope, tools, must-haves) but rewrite it fully into this guide's format, levels and voice.
If the input gives a different location, experience or reporting line, use the input."""

PROMPT = """You write job descriptions for LinkedERP. {about}

Follow this house guide exactly:
{guide}

Write the JD for the ROLE INPUT below in exactly the same structure, depth and voice as the EXAMPLES (they are real JDs from our library).

Return ONLY a JSON object with exactly these keys:
{{"title": str, "subtitle": str, "meta": [["Location", str], ["Employment Type", str], ["Experience Required", str], ["Reports To", str]],
 "overview": str, "responsibilities": [[area, text], ...], "skills": [str or [lead, text]], "preferred": [str], "qualities": [str], "offer": [str]}}

EXAMPLES:
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
        """Draft while the user waits (Odoo shows its loading screen) and reload the form, so the JD simply appears.
        If VectorMind is slow (over SYNC_WAIT seconds), the scheduled job finishes it and a pop-up tells the user."""
        recs = self.env["x_hiring_request"].browse(record_ids)
        for rec in recs:
            if not (rec.x_new_role_brief or rec.x_jd_file):
                raise UserError("Describe the new role in a few lines, or attach a sample JD, then click Draft JD with AI.")
        for rec in recs:
            try:
                self._draft(rec, wait=SYNC_WAIT)
            except Exception:
                _logger.info("JD helper: hiring request %s handed to the background job", rec.id, exc_info=True)
                rec.write({"x_ai_status": "requested", "x_ai_note": False})
                self.env.ref("linkederp_jd_helper.ir_cron_draft_jd")._trigger()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    # ---------- scheduled job ----------
    @api.model
    def _cron_draft_jds(self):
        for rec in self.env["x_hiring_request"].search([("x_ai_status", "=", "requested")], limit=10):
            try:
                self._draft(rec)
                self._notify(rec, "The JD for %s is ready. Open the hiring request to check it." % (rec.x_name or "the new role"), "success")
            except Exception as e:  # one bad request must not stop the rest
                _logger.exception("JD helper failed on hiring request %s", rec.id)
                rec.write({"x_ai_status": "failed", "x_ai_note": ("Could not draft: %s" % e)[:180]})
                self._notify(rec, "The AI helper could not draft the JD. Please try again.", "danger")
            self.env.cr.commit()

    def _notify(self, rec, message, kind):
        """Pop-up for whoever clicked the button (the last person to change the request)."""
        try:
            rec.write_uid.partner_id._bus_send("simple_notification", {
                "title": "AI helper", "message": message, "type": kind, "sticky": True})
        except Exception:  # a missed pop-up must never undo the JD
            _logger.info("JD helper: could not send the pop-up", exc_info=True)

    def _draft(self, rec, wait=None):
        sample = self._file_text(rec)
        parts = [rec.x_name and "Job title asked: %s" % rec.x_name,
                 rec.x_new_role_brief and "Description from the hiring manager: %s" % rec.x_new_role_brief,
                 sample and "Sample JD they attached:\n%s" % sample[:12000]]
        role = "\n".join(p for p in parts if p)
        if not role.strip():
            raise ValueError("nothing to work from, add a description or attach a sample JD")
        guide = self.env["ir.config_parameter"].sudo().get_param(P + "style_guide") or STYLE_GUIDE
        jd = parse_json(self._ask(PROMPT.format(about=ABOUT, guide=guide, example=self._examples(role), role=role), wait=wait))
        exp = dict((k, v) for k, v in jd.get("meta", [])).get("Experience Required", "")
        vals = {"x_about_role": jd_html(jd), "x_ai_status": "done", "x_ai_note": False}
        if not rec.x_name:
            vals["x_name"] = jd.get("title")
        if exp and not rec.x_experience:
            vals["x_experience"] = exp
        rec.write(vals)
        rec.message_post(body="JD drafted by the AI helper (VectorMind). Please check it before submitting.")

    def _examples(self, role_text):
        """The two library JDs closest to the input (shared words in the job title, level words count double)."""
        words = set(re.findall(r"[a-z]+", role_text.lower()))
        level = {"junior", "proficient", "senior"}
        jobs = self.env["hr.job"].search([("x_jd_library", "=", True)])

        def score(job):
            name = set(re.findall(r"[a-z]+", job.name.lower())) - {"consultant", "manager", "and", "the"}
            return sum(2 if w in level else 1 for w in name & words)

        best = sorted(jobs, key=lambda j: (-score(j), j.name != "Project Manager"))[:2]
        out = []
        for job in best:
            text = re.sub(r"<li>", "\n- ", str(job.description or ""))
            text = re.sub(r"<h3>", "\n\n## ", text)
            text = re.sub(r"\s*\n\s*", "\n", re.sub(r"<[^>]+>", " ", text)).strip()
            out.append("TITLE: %s\n%s" % (job.name, text[:5000]))
        return "\n\n=====\n\n".join(out)

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
    def _ask(self, content, wait=None):
        """wait=N: give up after N seconds (the user is watching); None: up to 5 minutes (background job)."""
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
            r = requests.post(api_ + "/external-messages", headers=h, timeout=wait or 150, json={
                "threadId": tid, "content": content, "contentType": "PlainText", "messageType": "User", "botId": bot,
                "searchWeb": False, "externalUserId": "hr-office", "stream": True})
            r.raise_for_status()
            return r.json().get("content", "")
        except (requests.Timeout, requests.HTTPError):
            if wait:
                raise
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
