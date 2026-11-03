==================================================
Slovakia - Peppol BIS Billing 3.0 (eFaktúra)
==================================================

Enables Peppol BIS Billing 3.0 (UBL 2.1 / EN 16931) e-invoice export for
Slovak companies, ahead of the mandatory Slovak e-invoicing regime
(domestic B2B from 1 January 2027).

Why this module is thin
=======================

Slovakia has **no national billing CIUS**. The mandated invoice is unmodified
Peppol BIS Billing 3.0, which Odoo's ``account.edi.xml.ubl_bis3`` already
produces correctly for a Slovak company. This module only fills the gaps:

* **Format registration.** ``SK`` is missing from Odoo core's
  ``PEPPOL_DEFAULT_COUNTRIES``, so the generic Peppol format is not offered or
  auto-suggested for Slovak partners. This module registers ``ubl_bis3_sk`` for
  ``SK`` and makes it the default ``invoice_edi_format`` for Slovak partners.
* **Extension point.** ``account.edi.xml.ubl_sk`` subclasses the generic Peppol
  builder, giving a stable place to add Slovak-specific behaviour later.
* **Variabilný symbol (VS).** Mapped onto ``cac:PaymentMeans/cbc:PaymentID``
  (BT-83): the explicit payment reference if set, otherwise the numeric tail of
  the invoice number.
* **BIS 3.0 terms core leaves out.** Filled only when Odoo holds the data:

  ======  ========================================  ======================================
  Term    UBL element                               Source in Odoo
  ======  ========================================  ======================================
  BT-25   ``BillingReference``                      credit note → ``reversed_entry_id``
  BT-30   ``PartyLegalEntity/CompanyID``            seller IČO (``company_registry``)
  BT-33   ``PartyLegalEntity/CompanyLegalForm``     company ``trade_registry``
  BT-47   ``PartyLegalEntity/CompanyID``            buyer IČO (``company_registry``)
  BT-72   ``Delivery/ActualDeliveryDate``           ``taxable_supply_date``
  BT-85   ``PayeeFinancialAccount/Name``            bank ``acc_holder_name``
  ======  ========================================  ======================================

  Core's UBL templates refuse elements they do not list, so the builder
  extends a deep copy of the template with ``CompanyLegalForm`` and
  ``FinancialAccount/Name``. To add another BIS 3.0 term, add its element to
  the template the same way, then fill it in the matching ``_ubl_add_*``
  hook. Stay inside Peppol BIS 3.0: other UBL 2.1 elements trigger the
  ``UBL-CR-*`` rules at the access point.

  BIS 3.0 terms with no Odoo field are not generated. They are listed in
  ``CHANGELOG.rst`` (18.0.3.2.0). BT-86 (BIC) comes from core once the
  company's bank account has a bank with a BIC.

Out of scope
============

The Slovak **Tax Data Document** (TDD, ``urn:peppol:taxdata:sk-1``) and the
5-corner CTC reporting to Finančná správa are the responsibility of a certified
Peppol Access Point, not the ERP.

Configuration
=============

Slovak partners get ``invoice_edi_format = "Slovakia (Peppol BIS 3.0)"``
automatically. Ensure the company has a valid IČ DPH (VAT) and a Slovak IBAN on
the relevant bank account.

Documentation
=============

* ``CHANGELOG.rst`` — release history.

Credits
=======

* Data Dance s.r.o. <https://www.datadance.eu>

License: AGPL-3.0 or later (see the LICENSE file).
