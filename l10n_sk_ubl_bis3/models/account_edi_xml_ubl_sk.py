# -*- coding: utf-8 -*-
import copy
import re

from odoo import _, models


def _template_insert_after(node, after, key):
    """Insert an empty ``key`` into template ``node`` right after ``after``.

    Templates fix the UBL element order, and ``dict_to_xml`` refuses a child
    they do not list — so a BIS 3.0 element core leaves out of the template
    cannot be emitted until it is added here, in its UBL 2.1 position.
    """
    if key in node:
        return
    items = list(node.items())
    position = [k for k, _v in items].index(after) + 1
    items.insert(position, (key, {}))
    node.clear()
    node.update(items)


class AccountEdiXmlUbl_Sk(models.AbstractModel):
    """Slovak flavour of Peppol BIS Billing 3.0.

    Slovakia has no national billing CIUS, so this builder is a near-empty
    subclass of the generic Peppol builder: the emitted XML (CustomizationID,
    ProfileID, party identification via EAS_MAPPING['SK'], VAT, IBAN, reverse
    charge) is already conformant. This class exists as a stable extension
    point and adds only the Slovak *variabilný symbol* convention.
    """
    _name = 'account.edi.xml.ubl_sk'
    _inherit = 'account.edi.xml.ubl_bis3'
    _description = "SK Peppol BIS Billing 3.0"

    def _export_invoice_filename(self, invoice):
        # OVERRIDE 'account.edi.xml.ubl_bis3'
        return f"{invoice.name.replace('/', '_')}_ubl_bis3_sk.xml"

    # NOTE: We deliberately do NOT override _get_customization_id /
    # _ubl_add_customization_id_node: Slovakia uses the plain Peppol BIS
    # Billing 3.0 CustomizationID, with no national CIUS deviation.

    # -------------------------------------------------------------------------
    # Slovak variabilný symbol (VS) -> cbc:PaymentID (BT-83)
    # -------------------------------------------------------------------------

    def _l10n_sk_get_variable_symbol(self, invoice):
        """Slovak VS: up to 10 digits used by banks to match incoming payments.

        A VS is numeric only, so normalise the source (the canonical
        l10n_cssk_payment_symbols field when installed, else an explicit
        payment_reference, otherwise the invoice number) to digits and
        keep the last 10. Falls back to the raw source if it has no digits.
        """
        source = ''
        if 'l10n_cssk_variable_symbol' in invoice._fields:
            source = invoice.l10n_cssk_variable_symbol or ''
        source = source or invoice.payment_reference or invoice.name or ''
        digits = re.sub(r'\D', '', source)
        return digits[-10:] if digits else source

    def _ubl_add_payment_means_nodes(self, vals):
        # EXTENDS 'account.edi.xml.ubl_bis3'
        super()._ubl_add_payment_means_nodes(vals)
        invoice = vals.get('invoice')
        if not invoice:
            return
        variable_symbol = self._l10n_sk_get_variable_symbol(invoice)
        for node in vals['document_node']['cac:PaymentMeans']:
            payment_id = node.get('cbc:PaymentID')
            if payment_id is not None:
                payment_id['_text'] = variable_symbol

    # -------------------------------------------------------------------------
    # Odoo 18 port: credit note -> original invoice (BT-25 / BT-26)
    # -------------------------------------------------------------------------

    def _ubl_add_billing_reference_nodes(self, vals):
        # EXTENDS 'account.edi.xml.ubl_bis3'
        # A Slovak corrective document must name the invoice it corrects
        # (§ 71 ods. 2 zákona o DPH; FS SR e-faktúra FAQ, príklad 50: BT-25).
        # 18.0 core fills BillingReference only for Dutch suppliers.
        super()._ubl_add_billing_reference_nodes(vals)
        invoice = vals.get('invoice')
        if not invoice or vals.get('document_type') != 'credit_note':
            return
        origin = invoice.reversed_entry_id
        if not origin or not origin.name or origin.name == '/':
            return
        nodes = vals['document_node']['cac:BillingReference']
        if any(
            (node.get('cac:InvoiceDocumentReference') or {}).get('cbc:ID', {}).get('_text') == origin.name
            for node in nodes
        ):
            return
        nodes.append({
            'cac:InvoiceDocumentReference': {
                'cbc:ID': {'_text': origin.name},
                'cbc:IssueDate': {'_text': origin.invoice_date},
            }
        })

    # -------------------------------------------------------------------------
    # Odoo 18 port: delivery date (BT-72) from the taxable supply date
    # -------------------------------------------------------------------------

    def _ubl_add_invoice_delivery_nodes(self, vals):
        # EXTENDS 'account.edi.ubl'
        # § 74 ods. 1 písm. d) wants the date of supply on every invoice; the
        # SK CIUS checks it as SK-R-012. 18.0 core emits cac:Delivery only for
        # a delivery address and dates it from ``delivery_date`` (19.0 carries
        # ``taxable_supply_date`` itself), so a plain service invoice went out
        # with no BT-72 at all.
        super()._ubl_add_invoice_delivery_nodes(vals)
        invoice = vals.get('invoice')
        if not invoice:
            return
        supply_date = (
            ('taxable_supply_date' in invoice._fields and invoice.taxable_supply_date)
            or invoice.delivery_date
            or invoice.invoice_date
        )
        if not supply_date:
            return
        nodes = vals['document_node']['cac:Delivery']
        if not nodes:
            nodes.append({'cbc:ActualDeliveryDate': {'_text': supply_date}})
        elif not nodes[0]['cbc:ActualDeliveryDate'].get('_text'):
            nodes[0]['cbc:ActualDeliveryDate']['_text'] = supply_date

    # -------------------------------------------------------------------------
    # BIS 3.0 terms core leaves out although Odoo holds the data
    # -------------------------------------------------------------------------

    def _get_document_template(self, vals):
        # EXTENDS 'account.edi.xml.ubl_20'
        # A deep copy: core's templates are module-level dicts shared by every
        # builder, so editing them in place would leak into other formats.
        template = copy.deepcopy(super()._get_document_template(vals))
        party = template['cac:AccountingSupplierParty']['cac:Party']
        _template_insert_after(party['cac:PartyLegalEntity'], 'cbc:CompanyID', 'cbc:CompanyLegalForm')
        account = template['cac:PaymentMeans']['cac:PayeeFinancialAccount']
        _template_insert_after(account, 'cbc:ID', 'cbc:Name')
        return template

    def _ubl_add_party_legal_entity_nodes(self, vals):
        # EXTENDS 'account.edi.xml.ubl_bis3'
        # BT-30 / BT-47: the legal registration identifier of a Slovak party is
        # its IČO. Core has no SK branch and falls back to the IČ DPH, which
        # the document already carries as BT-31 / BT-48.
        super()._ubl_add_party_legal_entity_nodes(vals)
        partner = vals['party_vals']['partner'].commercial_partner_id
        ico = re.sub(r'\s', '', partner.company_registry or '')
        if partner.country_code != 'SK' or not ico:
            return
        for node in vals['party_node']['cac:PartyLegalEntity']:
            node['cbc:CompanyID'] = {'_text': ico, 'schemeID': None}

    def _ubl_add_accounting_supplier_party_legal_entity_nodes(self, vals):
        # EXTENDS 'account.edi.ubl'
        # BT-33 Seller additional legal information: the commercial register
        # entry (§ 3a Obchodného zákonníka), kept by l10n_sk on the company.
        super()._ubl_add_accounting_supplier_party_legal_entity_nodes(vals)
        invoice = vals.get('invoice')
        legal_form = invoice and (invoice.company_id.trade_registry or '').strip()
        if not legal_form:
            return
        for node in vals['party_node']['cac:PartyLegalEntity']:
            node['cbc:CompanyLegalForm'] = {'_text': legal_form}

    def _ubl_get_payment_means_payee_financial_account_node_from_partner_bank(self, vals, partner_bank):
        # EXTENDS 'account.edi.ubl'
        # BT-85 Payment account name: the account holder, when recorded.
        node = super()._ubl_get_payment_means_payee_financial_account_node_from_partner_bank(vals, partner_bank)
        if node is not None and partner_bank.acc_holder_name:
            node['cbc:Name'] = {'_text': partner_bank.acc_holder_name}
        return node

    # -------------------------------------------------------------------------
    # A Slovak party must be identifiable before the document leaves
    # -------------------------------------------------------------------------

    def _export_invoice_constraints(self, invoice, vals):
        # EXTENDS 'account.edi.xml.ubl_bis3'
        constraints = super()._export_invoice_constraints(invoice, vals)
        constraints.update(self._l10n_sk_peppol_constraints(invoice, vals))
        return constraints

    def _export_invoice_constraints_new(self, invoice, vals):
        # EXTENDS 'account.edi.xml.ubl_bis3'
        # Odoo 18 port: 18.0 exports BIS3 through the "new" dict_to_xml path,
        # whose constraint hook is this one; ubl_bis3 calls the ubl_20 version
        # of _export_invoice_constraints from it, skipping our override above.
        constraints = super()._export_invoice_constraints_new(invoice, vals)
        constraints.update(self._l10n_sk_peppol_constraints(invoice, vals))
        return constraints

    def _l10n_sk_peppol_constraints(self, invoice, vals):
        """Refuse a Slovak party with no DIČ, here rather than at the gateway.

        The DIČ is no longer guessed from the VAT number, so a partner without
        one has no Slovak participant identifier — and the failure would
        otherwise surface at the access point as a *validation* error on an
        unknown participant, which reads as a malformed request and sends
        whoever is debugging it looking at the payload instead of at the
        contact. Worse, a partner with no DIČ keeps core's 9950 default and
        would go out under its IČ DPH, which is wrong but perfectly well
        formed, so nothing would complain at all.

        Named per party, so the message says which one to go and fix.
        """
        constraints = {}
        for role, partner in (
            ('supplier', invoice.company_id.partner_id.commercial_partner_id),
            ('customer', invoice.commercial_partner_id),
        ):
            if partner.country_code != 'SK':
                continue
            # Gated on the MISSING DIČ alone, not on the partner already being
            # on 0245. Gating on the scheme missed the case that matters: with
            # no DIČ recorded, _compute_peppol_eas never promotes the partner,
            # so it keeps core's 9950 default and sailed straight past this
            # check — exporting under the IČ DPH, which is the very bug this
            # module exists to fix. Measured on one real agenda: of 1204
            # Slovak trading partners with no DIČ, 1076 sat on 9950 and only
            # 127 on 0245, so the old gate caught about a tenth of them.
            #
            # A partner deliberately registered under another scheme is still
            # fine, as long as its DIČ is recorded — this asks for the number,
            # not for a particular scheme.
            if not partner._l10n_sk_get_dic():
                constraints[f'l10n_sk_ubl_bis3_{role}_dic_required'] = _(
                    "No DIČ is recorded for %(partner)s, so it has no Slovak "
                    "Peppol participant identifier: EAS 0245 carries the DIČ, "
                    "and it is currently published as %(eas)s. Set 'DIČ' on the "
                    "contact — it is not the VAT number and cannot be derived "
                    "from it.",
                    partner=partner.display_name,
                    eas=partner.peppol_eas or _("nothing"),
                )
        return constraints
