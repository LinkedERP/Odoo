# -*- coding: utf-8 -*-
import logging

from odoo import Command, _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def _get_refundable_expense_domain(self):
        """Domain for approved, employee-paid expenses flagged for payslip
        reimbursement that are not yet attached to any payslip.

        This mirrors the standard ``hr_payroll_expense`` gather logic (which only
        runs at payslip *creation*) and adds two defensive guards:
        ``company_id`` equality and ``account_move_id = False`` (no journal
        entry yet).

        It is intentionally NOT date-filtered, to preserve Odoo's
        "Reimburse in Next Payslip" semantics: a late-approved expense from an
        earlier period must still be reimbursed and not silently dropped. The
        attached expenses remain fully visible/reviewable on the draft payslip
        before it is validated.
        """
        self.ensure_one()
        return [
            ("employee_id", "=", self.employee_id.id),
            ("company_id", "=", self.company_id.id),
            ("payment_mode", "=", "own_account"),
            ("state", "=", "approved"),
            ("refund_in_payslip", "=", True),
            ("payslip_id", "=", False),
            ("account_move_id", "=", False),
        ]

    def _get_refundable_expenses(self):
        """Eligible expenses for THIS payslip. Returns an empty recordset for
        any non-draft payslip (safety)."""
        self.ensure_one()
        if self.state != "draft":
            return self.env["hr.expense"]
        return self.env["hr.expense"].search(self._get_refundable_expense_domain())

    # ------------------------------------------------------------------
    # Core refresh - safe, idempotent, draft-only
    # ------------------------------------------------------------------
    def _refresh_payslip_expenses(self):
        """Attach all eligible expenses to each *draft* payslip in ``self``.

        Returns a dict ``{payslip_id: attached hr.expense recordset}``.

        Guarantees:
          * non-draft payslips are skipped entirely;
          * only expenses with ``payslip_id = False`` are attached, so expenses
            already linked to another payslip are never stolen;
          * expenses are never detached;
          * attaching the same expense twice is impossible (idempotent).
        """
        attached_by_slip = {}
        for payslip in self:
            if payslip.state != "draft":
                continue
            expenses = payslip._get_refundable_expenses()
            if not expenses:
                continue
            # Standard relation: linking via the payslip's ``expense_ids`` o2m
            # sets ``hr.expense.payslip_id`` -- exactly what native Odoo does.
            payslip.write(
                {"expense_ids": [Command.link(exp.id) for exp in expenses]}
            )
            attached_by_slip[payslip.id] = expenses
            _logger.info(
                "mrelate_payroll_expense_integration: payslip %s attached "
                "expenses %s (total %.2f)",
                payslip.id, expenses.ids, sum(expenses.mapped("total_amount")),
            )
        return attached_by_slip

    # ------------------------------------------------------------------
    # Button: Refresh Expenses (corrective action for late approvals)
    # ------------------------------------------------------------------
    def action_refresh_expenses(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Expenses can only be refreshed on draft payslips."))

        attached = self._refresh_payslip_expenses().get(
            self.id, self.env["hr.expense"]
        )
        if attached:
            total = sum(attached.mapped("total_amount"))
            # Regenerate inputs/lines so the EXPENSES line reflects the new set.
            self.compute_sheet()
            self.message_post(
                body=_(
                    "<b>Refresh Expenses</b><br/>"
                    "%(count)s expense(s) added, total %(total)s %(currency)s.<br/>"
                    "Expense IDs: %(ids)s",
                    count=len(attached),
                    total="%.2f" % total,
                    currency=self.currency_id.name or "",
                    ids=", ".join(str(i) for i in attached.ids),
                )
            )
        else:
            self.message_post(
                body=_(
                    "<b>Refresh Expenses</b><br/>"
                    "No new approved reimbursable expenses were found."
                )
            )
        return True

    # ------------------------------------------------------------------
    # Auto-refresh on Compute (draft only) - optional convenience
    # ------------------------------------------------------------------
    def compute_sheet(self):
        """Before computing a *draft* payslip, pull in any eligible expenses
        approved after the payslip was created, so that clicking **Compute
        Sheet** naturally reimburses late-approved expenses.

        Non-draft payslips fall straight through to ``super`` unchanged.
        """
        draft_slips = self.filtered(lambda p: p.state == "draft")
        if draft_slips:
            draft_slips._refresh_payslip_expenses()
        return super().compute_sheet()
