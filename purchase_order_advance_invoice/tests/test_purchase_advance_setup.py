from odoo import Command
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseAdvanceSetup(AccountTestInvoicingCommon):
    """Where received advances show up, and which accounts they may book on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("purchase.group_purchase_manager")
        Account = cls.env["account.account"]
        cls.clearing = Account.create({
            "code": "314001", "name": "Paid advances clearing",
            "account_type": "liability_payable", "reconcile": True,
        })
        # As the Slovak chart has it: 314000 Poskytnuté preddavky is a receivable.
        cls.net_advance = Account.create({
            "code": "314000", "name": "Paid advances",
            "account_type": "asset_receivable", "reconcile": True,
        })
        cls.adv_journal = cls.env["account.journal"].create({
            "name": "Advance Tax Documents (Purchase)", "code": "PDADV", "type": "purchase",
        })
        cls.service = cls.env["product.product"].create({
            "name": "Advance service", "type": "service", "purchase_method": "purchase",
            "supplier_taxes_id": [Command.set(cls.company_data["default_tax_purchase"].ids)],
        })
        cls.spec = {
            "journal_code": "PDADV",
            "journal_name": "Advance Tax Documents (Purchase)",
            "accounts": {"paid_clearing": "314001", "paid_st": "314000", "paid_lt": ""},
        }

    def _orders_listed_by(self, xmlid):
        action = self.env.ref(xmlid)
        domain = safe_eval(action.domain or "[]")
        return self.env["purchase.order"].search(domain)

    def _order(self, **values):
        return self.env["purchase.order"].create(dict({
            "partner_id": self.partner_a.id,
            "order_line": [Command.create({
                "product_id": self.service.id, "product_qty": 1, "price_unit": 100.0,
            })],
        }, **values))

    def test_received_advances_stay_out_of_the_rfq_and_order_lists(self):
        rfq = self._order()
        order = self._order()
        order.button_confirm()
        advance = self._order(is_advance_invoice=True)
        paid_advance = self._order(is_advance_invoice=True)
        paid_advance.button_confirm()

        rfqs = self._orders_listed_by("purchase.purchase_rfq")
        orders = self._orders_listed_by("purchase.purchase_form_action")
        advances = self._orders_listed_by(
            "purchase_order_advance_invoice.action_purchase_order_advance"
        )
        self.assertIn(rfq, rfqs)
        self.assertIn(order, orders)
        self.assertNotIn(advance, rfqs)
        self.assertNotIn(paid_advance, orders)
        self.assertNotIn(order, advances)
        self.assertEqual(advances & (advance | paid_advance), advance | paid_advance)

    def test_a_receivable_paid_advances_account_becomes_a_current_asset(self):
        company = self.env.company
        company.advance_paid_account_id = False
        company._apply_purchase_advance_setup(self.spec)
        self.assertEqual(company.advance_paid_account_id, self.net_advance)
        self.assertEqual(self.net_advance.account_type, "asset_current")
        self.assertTrue(self.net_advance.reconcile)

    def test_the_tax_document_posts_on_the_slovak_chart_account(self):
        company = self.env.company
        company.advance_paid_account_id = False
        company.advance_paid_clearing_account_id = False
        company.advance_purchase_journal_id = False
        company._apply_purchase_advance_setup(self.spec)

        bank = self.company_data["default_journal_bank"]
        bank.outbound_payment_method_line_ids[:1].payment_account_id = self.env[
            "account.account"
        ].create({
            "code": "OUTPAY", "name": "Outstanding Payments",
            "account_type": "asset_current", "reconcile": True,
        })
        advance = self._order(is_advance_invoice=True)
        self.env["purchase.advance.payment.wizard"].with_context(
            active_model="purchase.order", active_id=advance.id,
        ).create({
            "journal_id": bank.id,
            "payment_method_line_id": bank.outbound_payment_method_line_ids[:1].id,
        }).action_create_payment()
        action = self.env["purchase.advance.tax.doc.wizard"].with_context(
            active_model="purchase.order", active_id=advance.id,
        ).create({"supplier_ref": "DOD-1"}).action_create()
        tax_doc = self.env["account.move"].browse(action["res_id"])
        tax_doc.action_post()
        self.assertEqual(tax_doc.state, "posted")
        self.assertIn(self.net_advance, tax_doc.line_ids.account_id)
