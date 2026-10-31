# -*- coding: utf-8 -*-
"""Recruitment room: candidates.

The AI reads each CV (fills the profile where empty, scores it against the JD) and, after each interview,
matches the Fathom recording to the candidate's round and writes notes for the panel. The panel decides.
Models are Studio-style (hr.applicant x_ fields, x_interview), so they are used through env at run time.
"""
import logging
import re
import time
from html import escape

import requests

from odoo import api, models
from odoo.exceptions import UserError

from .jd_helper import ABOUT, P, SYNC_WAIT, parse_json

_logger = logging.getLogger(__name__)

FATHOM = "https://api.fathom.ai/external/v1"

CV_PROMPT = """You screen CVs for LinkedERP. {about}

Read the CV below against the JD and this hire's needs. Return ONLY a JSON object:
{{"name": str, "email": str, "phone": str, "linkedin": str, "current_company": str, "designation": str,
 "total_experience_years": number, "relevant_experience_years": number, "location": str, "education": str,
 "skills": [str], "score": integer 0-100, "reasons": [3 short reasons for the score], "gaps": [what is missing against the JD]}}
Rules: take facts only from the CV; if something is not in the CV use "" or 0, never guess.
Score = fit for THIS role: 80+ strong, 60-79 possible, below 60 weak. Be strict on the required experience and must-have skills.
Plain, simple English.

JD:
{jd}

THIS HIRE: experience needed {exp}.

CV:
{cv}
"""

ROUND_PROMPT = """You help an interview panel at LinkedERP. {about}

Below is the transcript of the "{round}" interview with candidate {name} for the role {role}.
Read it against the JD and write notes for the panel. The panel decides; you only advise.
Return ONLY a JSON object:
{{"summary": "3 to 5 sentences", "strengths": [str], "concerns": [str], "suggestion": "Select" or "Reject" or "Unsure", "why": "one sentence"}}
Plain, simple English. Quote the candidate briefly where it helps.

JD:
{jd}

TRANSCRIPT:
{transcript}
"""


def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip()


def _ul(items):
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % escape(str(i)) for i in items or [] if i)


class LinkederpRecruitmentHelper(models.AbstractModel):
    _inherit = "linkederp.jd.helper"

    # ---------- CV: read, fill, score ----------
    @api.model
    def score_cvs(self, applicant_ids):
        """Button 'Read CV and score': runs while the user waits, falls back to the background job."""
        apps = self.env["hr.applicant"].browse(applicant_ids)
        for app in apps:
            if not app.x_cv:
                raise UserError("Upload the candidate's CV first (PDF or Word).")
        for app in apps:
            try:
                self._score_cv(app, wait=SYNC_WAIT)
            except Exception:
                _logger.info("CV score for applicant %s handed to the background job", app.id, exc_info=True)
                app.write({"x_ai_status": "requested", "x_ai_note": False})
                self.env.ref("linkederp_jd_helper.ir_cron_score_cv")._trigger()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    @api.model
    def queue_cvs(self, applicant_ids):
        """Called when a CV is uploaded: score in the background, no waiting."""
        self.env["hr.applicant"].browse(applicant_ids).write({"x_ai_status": "requested", "x_ai_note": False})
        self.env.ref("linkederp_jd_helper.ir_cron_score_cv")._trigger()
        return True

    @api.model
    def _cron_score_cvs(self):
        for app in self.env["hr.applicant"].search([("x_ai_status", "=", "requested")], limit=20):
            try:
                self._score_cv(app)
            except Exception as e:
                _logger.exception("CV score failed for applicant %s", app.id)
                app.write({"x_ai_status": "failed", "x_ai_note": ("Could not read the CV: %s" % e)[:180]})
            self.env.cr.commit()

    def _score_cv(self, app, wait=None):
        cv = self._binary_text(app.x_cv, app.x_cv_name)
        if not cv.strip():
            raise ValueError("no text found in the CV; upload a PDF or Word file that is not a scanned image")
        req = app.x_hiring_request_id
        jd = _strip(req.x_about_role if req else "") or _strip(app.job_id.description)
        exp = (req.x_experience if req else "") or "as in the JD"
        j = parse_json(self._ask(CV_PROMPT.format(about=ABOUT, jd=jd[:8000], exp=exp, cv=cv[:15000]), wait=wait))
        vals = {"x_ai_score": int(j.get("score") or 0), "x_ai_status": "done", "x_ai_note": False,
                "x_ai_reasons": "<p><b>Why this score</b></p>%s%s" % (
                    _ul(j.get("reasons")), ("<p><b>Gaps against the JD</b></p>" + _ul(j.get("gaps"))) if j.get("gaps") else "")}
        fill = {"partner_name": j.get("name"), "email_from": j.get("email"), "partner_phone": j.get("phone"),
                "linkedin_profile": j.get("linkedin"), "x_current_company": j.get("current_company"),
                "x_designation": j.get("designation"), "x_total_exp": j.get("total_experience_years"),
                "x_relevant_exp": j.get("relevant_experience_years"), "x_location": j.get("location"),
                "x_education": j.get("education")}
        for field, value in fill.items():  # never overwrite what HR already typed
            if value and not app[field]:
                vals[field] = value
        app.write(vals)
        app.message_post(body="AI read the CV: score %s/100. Profile fields filled where they were empty; please check them." % vals["x_ai_score"])

    # ---------- Fathom: match recordings to interview rounds ----------
    @api.model
    def fathom_now(self, round_ids=None):
        """Button 'Check Fathom now' on a round (also picks up a pasted Fathom link)."""
        self._cron_fathom(days=30)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    @api.model
    def _cron_fathom(self, days=14):
        key = (self.env["ir.config_parameter"].sudo().get_param(P + "fathom_api_key") or "").strip()
        if not key:
            return
        rounds = self.env["x_interview"].search([("x_decision", "=", "pending"), ("x_ai_notes", "=", False)], order="x_sequence")
        pasted = rounds.filtered("x_fathom_url")
        by_email = {}
        for rd in rounds - pasted:
            em = (rd.x_applicant_id.email_from or "").strip().lower()
            if em:
                by_email.setdefault(em, []).append(rd)  # earliest round first
        if not by_email and not pasted:
            return
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
        meetings, cursor = [], None
        for _ in range(10):
            params = {"created_after": since, "include_transcript": "true"}
            if cursor:
                params["cursor"] = cursor
            r = requests.get(FATHOM + "/meetings", headers={"X-Api-Key": key}, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            meetings += data.get("items", [])
            cursor = data.get("next_cursor")
            if not cursor:
                break
        for m in meetings:
            links = {m.get("share_url"), m.get("url")}
            for rd in pasted:
                if rd.x_fathom_url in links and not rd.x_ai_notes:
                    self._attach_recording(rd, m)
            emails = {(i.get("email") or "").lower() for i in m.get("calendar_invitees") or []}
            hits = [em for em in emails if by_email.get(em)]
            if len(hits) == 1:
                self._attach_recording(by_email[hits[0]].pop(0), m)
            elif len(hits) > 1:  # never guess between candidates
                for em in hits:
                    by_email[em][0].x_applicant_id.message_post(body=(
                        "A Fathom recording (%s) has more than one candidate invited, so it was not attached automatically. "
                        "Paste its link on the right round and click Check Fathom now." % (m.get("share_url") or m.get("url"))))

    def _attach_recording(self, rd, m):
        lines = []
        for t in m.get("transcript") or []:
            sp = t.get("speaker")
            who = sp.get("display_name") if isinstance(sp, dict) else sp
            lines.append("%s: %s" % (who or "Speaker", t.get("text", "")))
        app = rd.x_applicant_id
        req = app.x_hiring_request_id
        jd = _strip(req.x_about_role if req else "") or _strip(app.job_id.description)
        notes = "<p>No transcript in Fathom for this recording.</p>"
        if lines:
            j = parse_json(self._ask(ROUND_PROMPT.format(
                about=ABOUT, round=rd.x_name, name=app.partner_name, role=app.job_id.name or "",
                jd=jd[:6000], transcript="\n".join(lines)[:40000])))
            notes = ("<p>%s</p><p><b>Strengths</b></p>%s<p><b>Concerns</b></p>%s<p><b>AI suggestion: %s.</b> %s</p>"
                     "<p class='text-muted'>The panel decides. This is advice from the recording only.</p>") % (
                escape(j.get("summary", "")), _ul(j.get("strengths")), _ul(j.get("concerns")),
                escape(j.get("suggestion", "Unsure")), escape(j.get("why", "")))
        rd.write({"x_fathom_url": m.get("share_url") or m.get("url"),
                  "x_fathom_recording": str(m.get("recording_id") or ""), "x_ai_notes": notes})
        app.message_post(body="Fathom recording attached to %s, with AI notes for the panel." % rd.x_name)
        self.env.cr.commit()
