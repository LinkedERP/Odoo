from odoo import fields, models


class SaleOrderSla(models.Model):
    _inherit = "sale.order"

    # Per-contract monthly SLA hours allowance (Akshay maintains the value on
    # each support contract's SO). The Weekly Support & SLA Dashboard reads
    # it as the monthly target; every contract differs.
    sla_monthly_hours = fields.Float(
        string="Monthly SLA Hours Allowance",
        help="Support hours included per fiscal month (26th to 25th) for "
        "this SLA contract. Used by the Weekly Support & SLA Dashboard "
        "as the monthly consumption target.",
    )

    # Odoo-partnership retention (tier criterion 3): mark the outcome on each
    # Odoo renewal SO; the Odoo Partnership Tier dashboard computes
    # retention % = Renewed / (Renewed + Churned).
    odoo_renewal_outcome = fields.Selection(
        [("renewed", "Renewed"),
         ("churned", "Churned"),
         ("pending", "Pending")],
        string="Odoo Renewal Outcome",
        help="For Odoo subscription renewals: did the customer renew with "
        "us? Feeds the retention criterion on the Odoo Partnership Tier "
        "dashboard (Silver needs 70%, Gold 80%).",
    )
