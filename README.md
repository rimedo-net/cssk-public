# cssk-public

Czech and Slovak localization for Odoo, published by Data Dance s.r.o.

- [Slovak modules](https://www.datadance.eu/en/moduly/slovensko)
- [Czech modules](https://www.datadance.eu/en/moduly/cesko)
- [Licensing FAQ](https://www.datadance.eu/en/moduly/licencia)

**Generated from a private source repository.**

Every module here is produced from Data Dance's private source
repository, and each sync replaces what is on `19.0`. A change committed
directly to that branch is lost, not merged.

This branch, `18.0-sk-invoice`, is a cut of `19.0` for a Slovak invoicing
port to Odoo 18. It keeps the invoice, Peppol and sale-order advance
modules and drops the rest of the suite. Manifest dependencies are unchanged.
The module code is still the 19.0 source.

Pull requests to upstream are welcome on `19.0`: Data Dance applies an
accepted one to the source, keeping your authorship, and it returns in the
next sync. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Odoo 18 port (rimedo, branch `odoo18-port/peppol`)

The `18.0-sk-invoice` cut still carries 19.0 code and does not install on
Odoo 18. This branch makes the invoice and Peppol modules install and run on
18.0; see the commit for the list of changes. Ported and tested:
`l10n_cssk_core`, `l10n_cssk_payment_symbols`, `l10n_sk_base`,
`l10n_sk_invoice`, `l10n_sk_ubl_bis3`, `edi_base`, `edi_base_peppol`,
`edi_epostak_*`, plus the new `edi_ipostar_peppol` — 60 of 62 tests pass
(without iPoštár's 11, which all pass); the two `l10n_sk_invoice` failures
expect 19.0's "0% EU services" sale tax, which the 18.0 SK chart lacks.
Not touched: `sale_order_advance_invoice`, `l10n_sk_sale_order_advance_invoice`.
`migrations/19.0.*` never run on 18.0 versions.

### Receipt capture (branch `odoo18-port/receipt-capture`)

`l10n_cssk_receipt_capture`, `l10n_cssk_receipt_capture_expense` and
`l10n_sk_ekasa_receipt` are added from the 19.0 suite (cssk-public-mercor
`4508b2be`) and ported to 18.0 — 140 of 140 tests pass on 18.0 with `l10n_sk`
and `hr_expense`. What the port changes:

- manifests `18.0.x`; `_sql_constraints` instead of `models.Constraint`;
  the 19.0 `migrations/` of `l10n_cssk_receipt_capture` dropped;
- `l10n_cssk_receipt_capture_expense`: Odoo 18 posts expenses through
  `hr.expense.sheet`, so the per-VAT-rate split of the employee-paid bill moves
  from `hr.expense._prepare_receipts_vals` (19.0) to
  `hr.expense.sheet._prepare_bills_vals`, the "edited away from its receipt"
  check from `hr.expense.action_post` to `hr.expense.sheet._do_create_moves`
  (i.e. at approval); the company-paid entry takes its destination account
  from the sheet; `create_expense_from_attachments` returns an action in 18.0,
  so the uploaded expenses are found through their attachments; the 18.0
  expense form has no button box, the view adds one;
- tests: `groups_id`, expense report flow, users with an e-mail (18.0 refuses
  to post a message without one), `no_vat_validation` for a made-up VAT.

`l10n_cssk_receipt_capture_ai` (the LLM photo reader) is not part of the
suite; rimedo's `rdo_receipt_capture_claude` (rimedo addons) is a capture
provider on top of `rdo_bill_ocr_claude` instead. `l10n_sk_ekasa_receipt`
needs the Python package `zxing-cpp`.

## Modules

16 modules, licensed `AGPL-3`. Versions are the `19.0` manifests, except `edi_ipostar_peppol` (18.0 only).

### Slovak invoice

| Module | Version | What it does |
|---|---|---|
| `l10n_sk_base` | 19.0.2.0.0 | Slovak DIČ, distinct from IČ DPH and IČO. |
| `l10n_sk_invoice` | 19.0.1.0.4 | Statutory invoice PDF: DIČ, payment symbols, §74 phrases. |
| `l10n_cssk_payment_symbols` | 19.0.1.3.0 | Variable, constant and specific symbols on invoices. Shared CZ/SK dependency of `l10n_sk_invoice`. |
| `l10n_cssk_core` | 19.0.1.17.0 | Shared CZ/SK base. Declared dependency of `l10n_sk_invoice`. |
| `l10n_sk_ubl_bis3` | 19.0.3.1.0 | Peppol BIS Billing 3.0 / UBL export for Slovakia. |

### Peppol send (ePošťák, iPoštár)

| Module | Version | What it does |
|---|---|---|
| `edi_base` | 19.0.1.8.0 | Shared EDI transport. Depends on `account_add_gln`, which is not in this repository. |
| `edi_base_peppol` | 19.0.1.5.1 | Provider-neutral Peppol BIS Billing 3.0 send and receive. |
| `edi_epostak_base` | 19.0.1.0.1 | ePošťák access-point base. |
| `edi_epostak_connector_sapi` | 19.0.1.1.1 | ePošťák SAPI-SK 1.0 connector. |
| `edi_epostak_peppol` | 19.0.1.0.0 | Peppol BIS 3.0 through the ePošťák access point. |
| `edi_ipostar_peppol` | 18.0.1.0.0 | Peppol BIS 3.0 through the iPoštár access point (rimedo, not from the Data Dance source). |

### Fiscal receipt capture (bločky)

| Module | Version | What it does |
|---|---|---|
| `l10n_cssk_receipt_capture` | 18.0.1.1.1 | Captured receipt (lines, VAT recap), provider registry, reconciliation gates, vendor-receipt sink, camera QR scan. |
| `l10n_cssk_receipt_capture_expense` | 18.0.1.1.1 | Receipt → one `hr.expense` (per-rate VAT on the posted entry), capture on Expenses upload / scan. |
| `l10n_sk_ekasa_receipt` | 18.0.1.1.2 | eKasa QR → registered receipt from Finančná správa (§ 18 ods. 11 declaration, hourly budget). Needs `zxing-cpp`. |

### Sale-order advance invoices

| Module | Version | What it does |
|---|---|---|
| `sale_order_advance_invoice` | 19.0.2.7.1 | Advance invoices from sale orders, with a tax document on the received payment. |
| `l10n_sk_sale_order_advance_invoice` | 19.0.1.1.0 | Slovak chart wiring for those advance invoices (324/475). |

## Requirements outside this repository

Odoo: `account`, `mail`, `l10n_sk`, `account_edi_ubl_cii`, `sale`, `sale_management`, `account_payment`, `hr_expense` (receipt expense sink).

OCA: `account_add_gln` (dependency of `edi_base`).

Python: `requests`, `zxing-cpp` (`l10n_sk_ekasa_receipt`; QR decoding of receipt photos).
