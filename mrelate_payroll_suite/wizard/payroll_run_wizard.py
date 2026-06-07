# -*- coding: utf-8 -*-
"""Monthly Payroll Run wizard.

For each active employee in the selected company with an India payroll
structure type, in one click:
  1. Ensure a TDS declaration exists for the current FY (auto-create as draft).
  2. Refresh the salary projection from existing payslips.
  3. If declaration is in approved/locked state, re-apply monthly TDS to contract.
  4. Create a draft payslip for the period (skipped if a slip already exists).
  5. Create/refresh worked-days lines (Attendance, full working days from the
     resource calendar) and call compute_sheet.
  6. Refresh any approved reimbursable expenses onto the draft slip (via the
     standard expense_ids mechanism added by mrelate_payroll_expense_integration).
  7. Show a summary; HR reviews + validates payslips manually.

SAFETY:
  * Never validates / posts a payslip.
  * Never creates an accounting move.
  * Skips employees that already have a validated payslip for the period.
  * Skips employees not on an India structure type.
"""
import calendar
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PayrollRunWizard(models.TransientModel):
    _name = "mrelate.payroll.run.wizard"
    _description = "Monthly Payroll Run Wizard (India)"

    company_id = fields.Many2one(
        "res.company", required=True,
        default=lambda self: self.env.company)
    period_start = fields.Date(
        required=True,
        default=lambda self: self._default_period_start(),
        help="First day of the month to run payroll for.")
    period_end = fields.Date(
        required=True,
        default=lambda self: self._default_period_end(),
        help="Last day of the month to run payroll for.")
    struct_id = fields.Many2one(
        "hr.payroll.structure", required=True,
        domain="[('country_id.code', '=', 'IN')]",
        default=lambda self: self._default_struct(),
        help="Salary structure to apply (use the company's standard India structure).")
    apply_tds_if_approved = fields.Boolean(default=True,
        help="Re-apply each approved declaration's monthly TDS to its contract version.")
    create_missing_declarations = fields.Boolean(default=True,
        help="If an employee has no FY declaration yet, create one in DRAFT (HR fills later).")
    log_html = fields.Html(readonly=True,
        help="Audit log of what the run did - shown after Run completes.")
    employees_count = fields.Integer(readonly=True)
    declarations_created_count = fields.Integer(readonly=True)
    declarations_refreshed_count = fields.Integer(readonly=True)
    tds_applied_count = fields.Integer(readonly=True)
    payslips_created_count = fields.Integer(readonly=True)
    payslips_skipped_count = fields.Integer(readonly=True)
    expenses_attached_count = fields.Integer(readonly=True)

    # ------------------------------------------------------------------
    @api.model
    def _default_period_start(self):
        today = fields.Date.context_today(self)
        return today.replace(day=1)

    @api.model
    def _default_period_end(self):
        today = fields.Date.context_today(self)
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=last_day)

    @api.model
    def _default_struct(self):
        # Prefer a company-specific "<prefix> Regular Pay" structure if present.
        India = self.env["hr.payroll.structure"].search([
            ("country_id.code", "=", "IN"),
        ])
        # Pick a structure whose name contains "Regular Pay" first
        preferred = India.filtered(lambda s: "Regular Pay" in (s.name or ""))
        return (preferred[:1] or India[:1]).id

    # ------------------------------------------------------------------
    def _fy_string(self, ref_date):
        if ref_date.month >= 4:
            start = ref_date.year
        else:
            start = ref_date.year - 1
        return "%s-%s" % (start, str(start + 1)[-2:])

    def _india_employees(self):
        # All active employees in this company that have a hr.version with an
        # India structure type.
        India = self.env.ref("l10n_in_hr_payroll.payroll_structure_in_employee",
                             raise_if_not_found=False)
        emps = self.env["hr.employee"].search([
            ("company_id", "=", self.company_id.id),
            ("active", "=", True),
        ])
        out = self.env["hr.employee"]
        for e in emps:
            v = self.env["hr.version"].search([
                ("employee_id", "=", e.id),
                ("structure_type_id.country_id.code", "=", "IN"),
            ], order="date_version desc", limit=1)
            if v:
                out |= e
        return out

    def _version_for(self, employee, ref_date):
        # The active hr.version on the period date.
        v = self.env["hr.version"].search([
            ("employee_id", "=", employee.id),
            ("structure_type_id.country_id.code", "=", "IN"),
            "|", ("contract_date_start", "<=", ref_date),
                 ("contract_date_start", "=", False),
            "|", ("contract_date_end", ">=", ref_date),
                 ("contract_date_end", "=", False),
        ], order="date_version desc", limit=1)
        return v

    # ------------------------------------------------------------------
    def action_run(self):
        self.ensure_one()
        if self.period_start > self.period_end:
            raise UserError(_("Period start must be on or before period end."))
        if self.period_start.month != self.period_end.month:
            raise UserError(_("Period start and end must be within the same month."))

        fy = self._fy_string(self.period_start)
        emps = self._india_employees()
        Decl = self.env["mrelate.tds.declaration"]
        Payslip = self.env["hr.payslip"]
        WD = self.env["hr.payslip.worked_days"]

        log = []
        log.append("<h4>Monthly Payroll Run - %s %d (FY %s)</h4>"
                   % (calendar.month_name[self.period_start.month],
                      self.period_start.year, fy))
        log.append("<ul>")

        created = refreshed = applied = slips_new = slips_skipped = exp_attached = 0
        for emp in emps:
            version = self._version_for(emp, self.period_start)
            if not version or not version.wage:
                log.append("<li>%s: <i>SKIPPED</i> - no India contract version with wage</li>"
                           % emp.name)
                continue
            note = []

            # 1. Declaration
            decl = Decl.search([
                ("employee_id", "=", emp.id),
                ("financial_year", "=", fy),
                ("company_id", "=", self.company_id.id),
            ], limit=1)
            if not decl and self.create_missing_declarations:
                decl = Decl.create({
                    "employee_id": emp.id,
                    "version_id": version.id,
                    "company_id": self.company_id.id,
                    "financial_year": fy,
                    "regime": "new",  # legal default
                })
                created += 1
                note.append("decl auto-created (draft)")
            elif decl:
                # Refresh projection from existing payslips
                try:
                    decl.action_refresh_salary_projection()
                    refreshed += 1
                    note.append("projection refreshed")
                except Exception as e:
                    note.append("projection refresh failed: %s" % e)

            # 2. Apply TDS if approved
            if (self.apply_tds_if_approved and decl
                    and decl.state in ("approved", "locked")
                    and decl.version_id):
                try:
                    decl.action_apply_to_contract()
                    applied += 1
                    note.append("TDS Rs %0.0f applied to contract" % decl.monthly_tds)
                except Exception as e:
                    note.append("apply failed: %s" % e)

            # 3. Draft payslip for the period
            existing = Payslip.search([
                ("employee_id", "=", emp.id),
                ("date_from", "=", self.period_start),
                ("date_to", "=", self.period_end),
                ("company_id", "=", self.company_id.id),
            ], limit=1)
            if existing and existing.state != "draft":
                note.append("payslip exists (state=%s) - skipped" % existing.state)
                slips_skipped += 1
            else:
                if existing:
                    slip = existing
                    note.append("draft slip exists - recomputing")
                else:
                    slip = Payslip.create({
                        "employee_id": emp.id,
                        "version_id": version.id,
                        "struct_id": self.struct_id.id,
                        "date_from": self.period_start,
                        "date_to": self.period_end,
                        "company_id": self.company_id.id,
                        "name": "%s %d - %s" % (
                            calendar.month_name[self.period_start.month],
                            self.period_start.year, emp.name),
                    })
                    slips_new += 1
                    note.append("draft slip created")

                # Worked-days line if missing
                if not slip.worked_days_line_ids:
                    # Count working days in the period from the version's resource calendar
                    days, hours = self._working_days(version, self.period_start, self.period_end)
                    WD.create({
                        "name": "Attendance",
                        "work_entry_type_id": 1,  # standard Attendance
                        "payslip_id": slip.id,
                        "number_of_days": days,
                        "number_of_hours": hours,
                        "amount": version.wage,
                    })
                # 4. Expenses refresh (handled by compute_sheet override in expense module)
                try:
                    slip.compute_sheet()
                    if slip.expense_ids:
                        exp_attached += len(slip.expense_ids)
                except Exception as e:
                    note.append("compute failed: %s" % e)

            log.append("<li><b>%s</b>: %s</li>" % (emp.name, " | ".join(note) or "no-op"))

        log.append("</ul>")
        self.write({
            "log_html": "\n".join(log),
            "employees_count": len(emps),
            "declarations_created_count": created,
            "declarations_refreshed_count": refreshed,
            "tds_applied_count": applied,
            "payslips_created_count": slips_new,
            "payslips_skipped_count": slips_skipped,
            "expenses_attached_count": exp_attached,
        })
        # Return self to keep the wizard open showing the log
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrelate.payroll.run.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _working_days(self, version, start, end):
        """Counts business days in [start, end] using the version's resource
        calendar's weekly attendance pattern. Holidays/leaves not subtracted in
        Phase 1 - HR adjusts if needed. Returns (days, hours)."""
        cal = version.resource_calendar_id
        # Default: Mon-Fri 8h
        weekday_hours = {0: 8, 1: 8, 2: 8, 3: 8, 4: 8, 5: 0, 6: 0}
        if cal and cal.attendance_ids:
            # Build a map: weekday (0-6) -> total hours that day from the calendar
            weekday_hours = {i: 0.0 for i in range(7)}
            for att in cal.attendance_ids:
                try:
                    wd = int(att.dayofweek)
                except (TypeError, ValueError):
                    continue
                hours = (att.hour_to or 0.0) - (att.hour_from or 0.0)
                if hours > 0:
                    weekday_hours[wd] = weekday_hours.get(wd, 0.0) + hours

        days = 0
        hours = 0.0
        cur = start
        while cur <= end:
            wd_hours = weekday_hours.get(cur.weekday(), 0.0)
            if wd_hours > 0:
                days += 1
                hours += wd_hours
            cur = cur + timedelta(days=1)
        return days, hours
