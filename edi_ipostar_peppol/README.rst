=====================
iPoštár EDI: Peppol
=====================

Sends and receives **Peppol BIS Billing 3.0** invoices and credit notes
through the **iPoštár** access point (https://ipostar.app, OSTV s.r.o., REST
API documented at https://ipostar.app/vyvojari). It is a second Peppol
transport next to ePošťák and plugs into the neutral ``edi_base_peppol``
stack. The UBL itself (Slovak Peppol BIS 3.0, DIČ, VS) is produced by
``l10n_sk_ubl_bis3``; this module only delivers it.

How it works
============

=================  ==================================================  ============================================================
Direction          iPoštár API                                         Odoo
=================  ==================================================  ============================================================
Send               ``POST /invoices`` (raw UBL, ``X-API-Key``)         ``edi.message`` ``queued`` → ``sent`` (``edi_base`` send cron)
Delivery status    ``GET /invoices/{id}``: ``SENT`` / ``FAILED``,      cron *iPoštár: Query Outbound Delivery Status* →
                   MLS ``REJECTED``                                    ``done`` / ``error``
Receive            ``GET /inbox?from=…`` + ``GET /inbox/{id}/xml``     cron *iPoštár: Poll Inbound Documents* → draft vendor bill
=================  ==================================================  ============================================================

* **Errors.** 422 ``VALIDATION_FAILED`` puts the message in ``error`` with the
  failed Schematron rules, fatal ones first. 402 (out of credit), 429 and 5xx
  leave it ``queued``; the next cron run retries.
* **Size.** Documents over 5 MB are refused before they are sent.
* **Sandbox.** iPoštár has no separate test URL. A new account stays in
  sandbox until it is switched over in the customer zone; the API reports it
  and the message is flagged ``is_test_mode``. The sandbox test recipient is
  ``0245:9999999999``.
* **Receiving without an ack.** iPoštár has no acknowledge endpoint, and
  ``newForKey`` would mark a document read before Odoo has stored it. Each
  poll therefore re-reads the last *N* days (7 by default) and skips
  documents already stored (``provider_interchange_id``).

Configuration
=============

#. *Settings ▸ EDI ▸ iPoštár*: API key (``ipk_…``), optionally the API URL
   and the inbox look-back. **Test connection** calls ``GET /account``.
#. **Peppol Transport**: with ePošťák installed as well, pick *iPoštár* here.
   Left empty and with no other transport, iPoštár is used.
#. Company: enable e-invoice sending (``peppol_send_enabled``). Both the
   company and the customer need a Peppol address ``0245:<DIČ>``.
#. The company bank account must be **trusted** (``allow_out_payment``).
   Otherwise Odoo 18 drops it when confirming from the invoice, the invoice
   carries no IBAN and iPoštár rejects it (SK-R-011, fatal).

Tests
=====

``--test-tags /edi_ipostar_peppol``: HTTP is mocked, response shapes follow
the live API. One test sends UBL with an embedded PDF and checks that it
reaches iPoštár byte for byte.

Live-validated against the iPoštár sandbox, see ``CHANGELOG.rst``.

Credits
=======

* Rimedo, s.r.o. <https://rimedo.net>

License: AGPL-3.0 or later (see the LICENSE file).
