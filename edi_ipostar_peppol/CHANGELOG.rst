=========
Changelog
=========

All notable changes to **edi_ipostar_peppol** are documented here.
Versioning follows the Odoo manifest (``18.0.x.y.z``); format follows Keep a Changelog.

[18.0.1.1.0] — 2026-11-24
-------------------------

Fixed
~~~~~

- **Received invoices are no longer lost after an outage or a busy week.** The
  poll read a fixed 7-day window with at most 200 rows and no paging: an
  outage longer than 7 days, or more than 200 documents in the window, dropped
  documents silently. It now reads from one day before the last successful
  poll, splits a full listing into halves of the period until each fits, and
  downloads at most 200 new documents per run (then triggers itself again).
- The last successful poll is kept in ``ipostar.inbound.last_success`` and only
  moves once every new document is stored; the outcome of each poll is in
  ``ipostar.inbound.last_result``. Both are shown in *Settings ▸ EDI ▸ iPoštár
  ▸ Receiving*, where the date can be set back to read an older period again.
- Needs ``edi_base`` 18.0.1.9.0 (send cron commits per message, H2).

[18.0.1.0.0] — 2026-11-03
-------------------------

- Initial release, moved here from the private ``rdo_edi_ipostar``. Implements
  the ``edi_base_peppol`` transport hooks against the iPoštár REST API: send,
  delivery-status polling and inbound polling into draft vendor bills.
- Shares the **Peppol Transport** setting with ``edi_epostak_peppol``, so
  either module can pick the active transport.

- *Live-validated* against the iPoštár sandbox:

  - 2026-10-31: ``GET /account``; send to ``0245:9999999999`` →
    ``QUEUED`` → ``SENT`` with MLS ``AB`` → message ``done``; a 422 lists
    fatal rules first and stores warnings on the message.
  - 2026-11-02: a document sent to the company's own DIČ arrives in its own
    inbox and becomes a draft vendor bill with the embedded PDF intact.
    ``/inbox/{id}/xml`` returns the UBL as sent; ``/inbox/{id}/pdf`` is
    iPoštár's own preview, not the embedded PDF. A sent document cannot be
    downloaded back (``/invoices/{id}/xml`` is 404).
