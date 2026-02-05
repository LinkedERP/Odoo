{
    "name": "Contacts Missing Mandatory Info Report",
    "version": "1.0",
    "category": "Contacts",
    "summary": "Report of contacts missing email, phone and company",
    "depends": ["contacts"],
    "data": [
        "views/res_partner_report_views.xml",
        "views/duplicate_partner_contact.xml",
        "views/duplicate_partner_contact_views.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
}