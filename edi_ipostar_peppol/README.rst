=====================
iPoštár EDI: Peppol
=====================

Sends and receives **Peppol BIS Billing 3.0** invoices and credit notes
through the **iPoštár** access point (https://ipostar.app, OSTV s.r.o., REST
API documented at https://ipostar.app/vyvojari). It is a second Peppol
transport next to ePošťák and plugs into the neutral ``edi_base_peppol``
stack. The UBL itself (Slovak Peppol BIS 3.0, DIČ, VS) is produced by
``l10n_sk_ubl_bis3``; this module only delivers it.

Dependencies
============

* ``edi_base_peppol`` (→ ``edi_base``), and for Slovak invoices
  ``l10n_sk_ubl_bis3`` (UBL builder) and ``l10n_cssk_payment_symbols`` (VS).
* An iPoštár account and API key (``ipk_…``) from https://ipostar.app.
* Recommended: ``rdo_edi_peppol`` (rimedo rules: delivered invoice locked,
  correction by credit note, PDF embedded in the XML).

Installation
============

::

    docker compose run --rm odoo odoo -d <db> --stop-after-init -i \
      l10n_sk_base,l10n_cssk_payment_symbols,l10n_sk_invoice,l10n_sk_ubl_bis3,edi_base,edi_base_peppol,edi_ipostar_peppol

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

Usage
=====

#. Confirm a customer invoice for a partner with a Peppol address and press
   **Send via Peppol** (or let *Auto-send Peppol on Invoice Post* do it).
   The message is queued; the *EDI: send queued messages* cron (every 2
   minutes) posts it to iPoštár.
#. The invoice tab *Peppol Messages* and *EDI ▸ Messages* show the state:
   ``queued`` → ``sent`` → ``done`` (delivered) or ``error`` with the reason.
#. Received invoices appear as **draft vendor bills** in the Peppol purchase
   journal after the *iPoštár: Poll Inbound Documents* cron (every 30 minutes),
   with the embedded PDF attached.

Scheduled actions
=================

=====================================================  ==========
Cron                                                   Interval
=====================================================  ==========
EDI: send queued messages (``edi_base``)               2 minutes
iPoštár: Query Outbound Delivery Status                30 minutes
iPoštár: Poll Inbound Documents                        30 minutes
=====================================================  ==========

Known issues
============

* Inbox polling has no pagination: only the first 200 documents of the
  look-back window are read, and a polling outage longer than the window
  (7 days) loses documents silently.
* The send cron commits only at the end of its batch; a worker crash after
  some posts can resend them (iPoštár has no idempotency key).
* A non-UTF-8 inbound document stops the whole poll.
* ``ipostar.connector`` has no access rules (warning at start-up; it is only
  used through ``sudo``/cron).
* The company must be registered as a participant of the iPoštár account,
  otherwise sending fails with ``403 NOT_AUTHORIZED_PARTICIPANT``.

Tests
=====

``--test-tags /edi_ipostar_peppol``: HTTP is mocked, response shapes follow
the live API. One test sends UBL with an embedded PDF and checks that it
reaches iPoštár byte for byte.

Live-validated against the iPoštár sandbox, see ``CHANGELOG.rst``.

Slovensky (stručne)
===================

**Na čo slúži:** odosiela a prijíma e-faktúry (Peppol BIS 3.0) cez prístupový
bod iPoštár. Faktúra sa po kliknutí *Odoslať cez Peppol* zaradí do fronty
a do 2 minút odíde; stav doručenia sa overuje každých 30 minút. Prijaté
e-faktúry sa každých 30 minút stiahnu ako koncepty dodávateľských faktúr
aj s PDF.

**Nastavenie:** *Nastavenia ▸ EDI ▸ iPoštár* – API kľúč (``ipk_…``),
**Test connection** (overí účet a režim sandbox/produkcia), *Peppol Transport*
= iPoštár. Firma: zapnuté posielanie e-faktúr, Peppol adresa ``0245:<DIČ>``
registrovaná v účte iPoštáru, bankový účet označený ako dôveryhodný.

**Obmedzenia:** sandbox simuluje doručenie (testovací príjemca
``0245:9999999999``); príjem bez stránkovania a s pevným oknom 7 dní – pozri
*Known issues*.

Credits
=======

* Rimedo, s.r.o. <https://rimedo.net>

License: AGPL-3.0 or later (see the LICENSE file).
