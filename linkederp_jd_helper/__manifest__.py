# -*- coding: utf-8 -*-
{
    "name": "LinkedERP JD Helper (VectorMind)",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Recruitment",
    "summary": "Drafts a job description in LinkedERP's format from a short description or a sample JD, using VectorMind.",
    "description": """
LinkedERP JD Helper
===================
HR Office, Recruitment room. The "Draft JD with AI" button on a hiring request (x_hiring_request) calls
``linkederp.jd.helper.request_draft``. A scheduled job is triggered at once, asks VectorMind (BusinessGPT,
LinkedERP's approved AI) for the JD as JSON, renders it in the JD library layout and writes it into
"About the role".

Settings (System Parameters):
* linkederp_jd_helper.vm_client_id
* linkederp_jd_helper.vm_client_secret
* linkederp_jd_helper.vm_bot_id (optional, default gpt-5.5 bot)
""",
    "author": "LinkedERP",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": ["data/ir_cron.xml"],
    "installable": True,
    "application": False,
}
