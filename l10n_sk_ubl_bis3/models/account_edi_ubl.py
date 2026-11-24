# -*- coding: utf-8 -*-
"""Import fix: the supplier's IBAN from a received UBL.

Odoo 18.0 (``account_edi_ubl_cii``, the ``collected_values`` importer) looks
the partner up under ``collected_values['customer']``, but the importer
stores it in ``collected_values['customer_values']['customer']``. The partner
is therefore always missing there, and ``PayeeFinancialAccount/ID`` (BT-84)
never reaches the bill: a received e-invoice comes in without the account to
pay it to. Expose the partner under the key the bank lookup reads.
"""
from odoo import models


class AccountEdiUBL(models.AbstractModel):
    _inherit = 'account.edi.ubl'

    def _import_ubl_retrieve_partner_bank(self, collected_values):
        if not collected_values.get('customer'):
            partner = (collected_values.get('customer_values') or {}).get('customer')
            if not partner:
                # A partner the importer has just created is only in to_write.
                partner_id = (collected_values.get('to_write') or {}).get('partner_id')
                partner = self.env['res.partner'].browse(partner_id) if partner_id else None
            if partner:
                collected_values['customer'] = partner
        return super()._import_ubl_retrieve_partner_bank(collected_values)
