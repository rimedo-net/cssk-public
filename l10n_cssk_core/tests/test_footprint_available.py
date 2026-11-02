from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFootprintAvailable(TransactionCase):
    """The footprint button only shows when a report module fills it."""

    def test_no_contributor_hides_the_button(self):
        AML = self.env["account.move.line"]
        cls = type(AML)
        from odoo.addons.l10n_cssk_core.models.account_move_line import AccountMoveLine
        if cls._cssk_statutory_footprint is not AccountMoveLine._cssk_statutory_footprint:
            self.skipTest("a footprint contributor is installed")
        self.assertFalse(AML._cssk_footprint_has_contributor())
        move = self.env["account.move"].new({"move_type": "entry"})
        self.assertFalse(move.cssk_footprint_available)

    def test_a_contributor_shows_the_button(self):
        AML = self.env["account.move.line"]
        with patch.object(type(AML), "_cssk_statutory_footprint", lambda self: []):
            self.assertTrue(AML._cssk_footprint_has_contributor())
            move = self.env["account.move"].new({"move_type": "entry"})
            self.assertTrue(move.cssk_footprint_available)
