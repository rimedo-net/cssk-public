=========
Changelog
=========

All notable changes to **edi_ipostar_peppol** are documented here.
Versioning follows the Odoo manifest (``18.0.x.y.z``); format follows Keep a Changelog.

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
