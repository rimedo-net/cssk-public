# -*- coding: utf-8 -*-
"""Our format is known wherever core keys the Peppol CustomizationID by format."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSlovakCustomizationIds(TransactionCase):

    def test_ubl_bis3_sk_is_plain_bis3(self):
        """account_peppol looks the partner's format up in this map when it
        verifies a partner; a missing key was a KeyError on every Slovak
        partner registered on Peppol, raised from res.partner create/write."""
        ubl = self.env['account.edi.xml.ubl_21']
        self.assertEqual(ubl._get_customization_ids()['ubl_bis3_sk'],
                         ubl._get_customization_ids()['ubl_bis3'])
        self.assertEqual(ubl._get_selfbilling_customization_ids()['ubl_bis3_sk'],
                         ubl._get_selfbilling_customization_ids()['ubl_bis3'])

    def test_our_peppol_format_has_a_customization_id(self):
        formats = self.env['res.partner']._get_peppol_formats()
        self.assertIn('ubl_bis3_sk', formats)
        self.assertIn('ubl_bis3_sk', self.env['account.edi.xml.ubl_21']._get_customization_ids())
