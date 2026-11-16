"""What the customer and the user see of an advance: its amounts and its date."""

from datetime import datetime

from lxml import etree

from odoo.tests import tagged

from .common import AdvanceInvoiceCommon


@tagged("post_install", "-at_install")
class TestAdvanceDisplay(AdvanceInvoiceCommon):

    def _fixed_advance(self, amount=300.0):
        order = self._order()
        advance = self._advance(order, method="fixed", fixed_amount=amount)
        return order, advance

    def test_the_printed_advance_shows_its_line_amount(self):
        # Odoo 19 hides the amount of down-payment lines in an inner <t>; every
        # line of an advance is one, so the print showed no amount at all.
        _order, advance = self._fixed_advance(300.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", advance.ids
        )[0].decode()
        cells = etree.HTML(html).xpath("//td[@name='td_product_subtotal']")
        self.assertTrue(cells)
        # The advance prints without a Taxes column, so with the tax included.
        expected = "%.2f" % advance.order_line.price_total
        self.assertTrue(
            any(expected in "".join(cell.itertext()) for cell in cells),
            "the advance line amount %s is printed" % expected,
        )

    def test_a_regular_order_still_hides_its_down_payment_amounts(self):
        order, _advance = self._fixed_advance()
        tracking = order.order_line.filtered("is_advance_tracking").filtered(
            lambda line: not line.display_type
        )
        html = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", order.ids
        )[0].decode()
        self.assertTrue(tracking)
        self.assertEqual(
            html.count('name="td_product_subtotal"'),
            len(order.order_line.filtered(lambda line: not line.display_type)),
            "every product row keeps its amount cell, the columns stay aligned",
        )

    def test_the_form_shows_the_amount_on_advance_lines(self):
        arch = self.env["sale.order"].get_views([(False, "form")])["views"]["form"]["arch"]
        amounts = etree.fromstring(arch).xpath(
            "//field[@name='order_line']/list/field[@name='price_subtotal']"
        )
        self.assertTrue(amounts)
        for field in amounts:
            self.assertIn("parent.is_advance_invoice", field.get("invisible", ""))

    def test_confirming_an_advance_keeps_its_issue_date(self):
        _order, advance = self._fixed_advance()
        issued = datetime(2026, 10, 27, 9, 0)
        advance.date_order = issued
        advance.action_confirm()
        self.assertEqual(advance.state, "sale")
        self.assertEqual(advance.date_order, issued)

    def test_confirming_an_order_still_dates_it_now(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "date_order": datetime(2026, 1, 1, 9, 0),
            "order_line": [(0, 0, {"product_id": self.printer.id, "price_unit": 10.0})],
        })
        order.action_confirm()
        self.assertGreater(order.date_order, datetime(2026, 1, 1, 9, 0))

    def test_the_tracking_line_names_the_issue_date_first(self):
        order, advance = self._fixed_advance()
        advance.date_order = datetime(2026, 10, 27, 9, 0)
        advance.action_confirm()
        order._sync_advance_tracking_line_from_advance(advance)
        tracking = order.order_line.filtered(
            lambda line: line.advance_source_order_id == advance
        )
        self.assertRegex(
            tracking.name,
            r"^Advance Invoice %s of .*2026" % advance.name,
        )
