# Copyright 2026 Data Dance s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Odoo 18 only: expenses are posted through an expense report.

In Odoo 19 the report is gone and ``hr.expense`` builds its own vendor receipt
(``_prepare_receipts_vals``) and checks itself in ``action_post``. In Odoo 18
the employee-paid document is the report's vendor bill
(``hr.expense.sheet._prepare_bills_vals``) and the moves are created in
``_do_create_moves``, so the same two hooks sit here.
"""
from odoo import Command, models


class HrExpenseSheet(models.Model):
    _inherit = "hr.expense.sheet"

    def _do_create_moves(self):
        self.expense_line_ids._cssk_check_all_parts()
        return super()._do_create_moves()

    def _prepare_bills_vals(self):
        """Employee-paid: the vendor bill carries one line per VAT rate.

        Each line keeps ``expense_id``, so ``hr_expense`` still treats its
        amount as tax-included, and the bill's partner, account, analytic and
        product are those Odoo chose for the expense's single line.
        """
        vals = super()._prepare_bills_vals()
        lines = []
        for command in vals.get("line_ids", []):
            line = command[2] if len(command) > 2 and isinstance(command[2], dict) else {}
            expense = (self.env["hr.expense"].browse(line["expense_id"])
                       if line.get("expense_id") else None)
            parts = expense._cssk_rate_parts() if expense else None
            if not parts:
                lines.append(command)
                continue
            expense._cssk_check_parts(parts)
            for (_gross, tax, rate), amount in zip(
                    parts, expense._cssk_company_amounts(parts)):
                lines.append(Command.create(dict(
                    line, quantity=1, price_unit=amount,
                    tax_ids=[Command.set(tax.ids)],
                    name="%s (%g %%)" % (line.get("name") or "", rate))))
        vals["line_ids"] = lines
        return vals
