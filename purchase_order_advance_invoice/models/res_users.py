from odoo import _, api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _get_activity_groups(self):
        """Split the purchase.order group of the systray activity menu: advance
        invoices get their own entry, so the user does not have to look for
        them among regular orders (and vice versa)."""
        groups = super()._get_activity_groups()
        group = next((g for g in groups if g.get("model") == "purchase.order"), None)
        if not group:
            return groups
        activities = self.env["mail.activity"].search(
            [("user_id", "=", self.env.uid), ("res_model", "=", "purchase.order")]
        )
        by_record = activities.grouped("res_id")
        # Keep only records the core group counted (existing + readable)
        records = (
            self.env["purchase.order"].browse(list(by_record)).exists()._filtered_access("read")
        )
        advance = records.filtered("is_advance_invoice")
        if not advance:
            group["domain"] = [*group["domain"], ("is_advance_invoice", "=", False)]
            return groups

        def _counts(recs):
            counts = dict.fromkeys(
                ("overdue_count", "today_count", "planned_count", "total_count"), 0
            )
            for rec in recs:
                states = by_record[rec.id].mapped("state")
                # Same precedence as mail's _get_activity_groups
                state = next(
                    (s for s in ("overdue", "today") if s in states), "planned"
                )
                counts[f"{state}_count"] += 1
                if state != "planned":
                    counts["total_count"] += 1
            return counts

        advance_group = dict(
            group,
            name=_("Received Advance Invoices"),
            domain=[*group["domain"], ("is_advance_invoice", "=", True)],
            **_counts(advance),
        )
        regular = records - advance
        index = groups.index(group)
        if regular:
            group.update(_counts(regular))
            group["domain"] = [*group["domain"], ("is_advance_invoice", "=", False)]
            groups.insert(index + 1, advance_group)
        else:
            groups[index] = advance_group
        return groups
