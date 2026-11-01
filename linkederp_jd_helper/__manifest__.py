# -*- coding: utf-8 -*-
{
    "name": "LinkedERP JD Helper (VectorMind)",
    "version": "19.0.1.6.0",
    "category": "Human Resources/Recruitment",
    "summary": "HR Office recruitment helpers with VectorMind: drafts JDs, reads and scores CVs, attaches Fathom interview notes.",
    "description": """
LinkedERP JD Helper
===================
HR Office, Recruitment room. The "Draft JD with AI" button on a hiring request (x_hiring_request) calls
``linkederp.jd.helper.request_draft``, which drafts while the user waits (the form reloads with the JD) or, if VectorMind is slow, hands it to a scheduled job that sends a pop-up when done. It asks VectorMind (BusinessGPT,
LinkedERP's approved AI) for the JD as JSON, renders it in the JD library layout and writes it into
"About the role".

Settings (System Parameters):
* linkederp_jd_helper.vm_client_id
* linkederp_jd_helper.vm_client_secret
* linkederp_jd_helper.vm_bot_id (optional, default gpt-5.5 bot)
""",
    "author": "LinkedERP",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web"],
    "data": ["data/ir_cron.xml", "data/hr_office.xml"],
    "assets": {
        "web.assets_backend": [
            "linkederp_jd_helper/static/src/cv_dropzone.js",
            "linkederp_jd_helper/static/src/cv_dropzone.xml",
            "linkederp_jd_helper/static/src/hr_office.js",
            "linkederp_jd_helper/static/src/hr_office.xml",
            "linkederp_jd_helper/static/src/hr_office.scss",
        ],
    },
    "installable": True,
    "application": False,
}
