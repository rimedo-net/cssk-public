# -*- coding: utf-8 -*-
import re

from lxml import etree

from odoo import Command
from odoo.tests import tagged
from odoo.addons.l10n_account_edi_ubl_cii_tests.tests.common import TestUBLCommon

NS = {
    'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    'cac': "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
PEPPOL_BILLING_CUSTOMIZATION_ID = (
    'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0'
)


@tagged('post_install', '-at_install')
class TestUBLSlovakia(TestUBLCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sk_country = cls.env.ref('base.sk')
        cls.eur = cls.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', 'EUR')], limit=1)
        cls.eur.active = True

        cls.seller = cls.env['res.partner'].create({
            'name': "SK Seller s.r.o.",
            'street': "Hlavna 1",
            'zip': "81101",
            'city': "Bratislava",
            'country_id': cls.sk_country.id,
            'vat': "SK2020000004",
            'company_registry': "12345679",
            'bank_ids': [Command.create({
                'acc_number': "SK3112000000198742637541",
                'allow_out_payment': True,  # trusted, so posting doesn't raise
            })],
        })
        cls.buyer = cls.env['res.partner'].create({
            'name': "SK Buyer a.s.",
            'street': "Vedlajsia 2",
            'zip': "04001",
            'city': "Kosice",
            'country_id': cls.sk_country.id,
            'vat': "SK2020000015",
        })

    # -------------------------------------------------------------------------
    # Format registration / auto-selection plumbing
    # -------------------------------------------------------------------------

    def test_format_is_registered_for_slovakia(self):
        info = self.env['res.partner']._get_ubl_cii_formats_info()
        self.assertIn('ubl_bis3_sk', info)
        self.assertEqual(info['ubl_bis3_sk']['countries'], ['SK'])
        self.assertTrue(info['ubl_bis3_sk']['on_peppol'])

    def test_builder_mapping(self):
        builder = self.buyer._get_edi_builder('ubl_bis3_sk')
        self.assertEqual(builder._name, 'account.edi.xml.ubl_sk')
        self.assertEqual(builder._description, "SK Peppol BIS Billing 3.0")

    def test_sk_partner_auto_suggests_sk_format(self):
        # Single format for SK -> it is the suggested one for Slovak partners.
        self.assertEqual(self.buyer._get_suggested_ubl_cii_edi_format(), 'ubl_bis3_sk')
        self.assertEqual(self.buyer._get_suggested_invoice_edi_format(), 'ubl_bis3_sk')

    # -------------------------------------------------------------------------
    # Export content
    # -------------------------------------------------------------------------

    def test_export_is_plain_peppol_bis3_with_sk_specifics(self):
        invoice = self._generate_move(
            self.seller, self.buyer, send=False,
            move_type='out_invoice',
            currency_id=self.eur.id,
            invoice_line_ids=[{
                'product_id': self.product_a.id,
                'quantity': 1,
                'price_unit': 100.0,
                'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
            }],
        )

        builder = self.env['account.edi.xml.ubl_sk']
        xml_bytes, _errors = builder._export_invoice(invoice)
        tree = etree.fromstring(xml_bytes)

        # 1. Plain Peppol BIS Billing 3.0 — no SK CIUS deviation.
        self.assertEqual(
            tree.findtext('cbc:CustomizationID', namespaces=NS),
            PEPPOL_BILLING_CUSTOMIZATION_ID,
        )

        # 2. Slovak IC DPH appears as SK########## in the supplier PartyTaxScheme
        #    (country-prefixed, no schemeID) — the EN16931 convention.
        supplier_vat = tree.findtext(
            'cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID',
            namespaces=NS,
        )
        self.assertEqual(supplier_vat, "SK2020000004")

        # 3. IBAN flows to the payee financial account.
        iban = tree.findtext(
            'cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID', namespaces=NS)
        self.assertEqual((iban or '').replace(' ', ''), "SK3112000000198742637541")

        # 4. Variabilný symbol -> cbc:PaymentID (digits of the invoice number).
        expected_vs = re.sub(r'\D', '', invoice.name)[-10:]
        self.assertEqual(
            tree.findtext('cac:PaymentMeans/cbc:PaymentID', namespaces=NS),
            expected_vs,
        )

    def test_export_filename(self):
        invoice = self._generate_move(
            self.seller, self.buyer, send=False,
            move_type='out_invoice',
            currency_id=self.eur.id,
            invoice_line_ids=[{
                'product_id': self.product_a.id,
                'quantity': 1,
                'price_unit': 100.0,
                'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
            }],
        )
        filename = self.env['account.edi.xml.ubl_sk']._export_invoice_filename(invoice)
        self.assertTrue(filename.endswith('_ubl_bis3_sk.xml'))

    # -------------------------------------------------------------------------
    # BIS 3.0 terms filled from data Odoo already holds
    # -------------------------------------------------------------------------

    def _export_tree(self, move_type='out_invoice'):
        invoice = self._generate_move(
            self.seller, self.buyer, send=False,
            move_type=move_type,
            currency_id=self.eur.id,
            invoice_line_ids=[{
                'product_id': self.product_a.id,
                'quantity': 1,
                'price_unit': 100.0,
                'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
            }],
        )
        # The fixtures carry no DIČ, so the constraint errors are expected;
        # the document is still rendered, which is what is under test here.
        xml_bytes, _errors = self.env['account.edi.xml.ubl_sk']._export_invoice(invoice)
        return etree.fromstring(xml_bytes)

    def test_export_legal_form_ico_and_account_name(self):
        self.env.company.trade_registry = (
            "Obchodný register Mestského súdu Bratislava III, oddiel: Sro, vložka č. 166533/B"
        )
        self.seller.bank_ids.acc_holder_name = "SK Seller s.r.o."
        self.buyer.company_registry = "87654326"

        tree = self._export_tree()
        supplier = tree.find('cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity', NS)
        customer = tree.find('cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity', NS)
        account = tree.find('cac:PaymentMeans/cac:PayeeFinancialAccount', NS)

        # BT-30 / BT-47: IČO, not the IČ DPH (that is BT-31 / BT-48).
        self.assertEqual(supplier.findtext('cbc:CompanyID', namespaces=NS), "12345679")
        self.assertEqual(customer.findtext('cbc:CompanyID', namespaces=NS), "87654326")
        # BT-33, after CompanyID as UBL 2.1 orders it.
        self.assertEqual(
            supplier.findtext('cbc:CompanyLegalForm', namespaces=NS),
            self.env.company.trade_registry,
        )
        self.assertEqual(
            [etree.QName(child).localname for child in supplier],
            ['RegistrationName', 'CompanyID', 'CompanyLegalForm'],
        )
        # BT-33 is a seller term only.
        self.assertIsNone(customer.find('cbc:CompanyLegalForm', NS))
        # BT-85, between the account ID and the branch.
        self.assertEqual(account.findtext('cbc:Name', namespaces=NS), "SK Seller s.r.o.")
        self.assertEqual(etree.QName(account[1]).localname, 'Name')

    def test_export_without_the_data_emits_nothing_new(self):
        self.env.company.trade_registry = False
        self.seller.bank_ids.acc_holder_name = False
        self.seller.company_registry = False

        tree = self._export_tree()
        supplier = tree.find('cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity', NS)
        self.assertIsNone(supplier.find('cbc:CompanyLegalForm', NS))
        self.assertEqual(supplier.findtext('cbc:CompanyID', namespaces=NS), "SK2020000004")
        self.assertIsNone(tree.find('cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:Name', NS))

    def test_credit_note_carries_the_same_terms(self):
        self.env.company.trade_registry = "OR OS Bratislava I, oddiel Sro, vložka 1/B"
        tree = self._export_tree(move_type='out_refund')
        self.assertEqual(etree.QName(tree).localname, 'CreditNote')
        self.assertEqual(
            tree.findtext(
                'cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyLegalForm',
                namespaces=NS,
            ),
            "OR OS Bratislava I, oddiel Sro, vložka 1/B",
        )
