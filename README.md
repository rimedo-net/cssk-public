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

## Modules

12 modules, licensed `AGPL-3`. Versions are the `19.0` manifests.

### Slovak invoice

| Module | Version | What it does |
|---|---|---|
| `l10n_sk_base` | 19.0.2.0.0 | Slovak DIČ, distinct from IČ DPH and IČO. |
| `l10n_sk_invoice` | 19.0.1.0.4 | Statutory invoice PDF: DIČ, payment symbols, §74 phrases. |
| `l10n_cssk_payment_symbols` | 19.0.1.3.0 | Variable, constant and specific symbols on invoices. Shared CZ/SK dependency of `l10n_sk_invoice`. |
| `l10n_cssk_core` | 19.0.1.17.0 | Shared CZ/SK base. Declared dependency of `l10n_sk_invoice`. |
| `l10n_sk_ubl_bis3` | 19.0.3.1.0 | Peppol BIS Billing 3.0 / UBL export for Slovakia. |

### Peppol send (ePošťák)

| Module | Version | What it does |
|---|---|---|
| `edi_base` | 19.0.1.8.0 | Shared EDI transport. Depends on `account_add_gln`, which is not in this repository. |
| `edi_base_peppol` | 19.0.1.5.1 | Provider-neutral Peppol BIS Billing 3.0 send and receive. |
| `edi_epostak_base` | 19.0.1.0.1 | ePošťák access-point base. |
| `edi_epostak_connector_sapi` | 19.0.1.1.1 | ePošťák SAPI-SK 1.0 connector. |
| `edi_epostak_peppol` | 19.0.1.0.0 | Peppol BIS 3.0 through the ePošťák access point. |

### Sale-order advance invoices

| Module | Version | What it does |
|---|---|---|
| `sale_order_advance_invoice` | 19.0.2.7.1 | Advance invoices from sale orders, with a tax document on the received payment. |
| `l10n_sk_sale_order_advance_invoice` | 19.0.1.1.0 | Slovak chart wiring for those advance invoices (324/475). |

## Requirements outside this repository

Odoo: `account`, `mail`, `l10n_sk`, `account_edi_ubl_cii`, `sale`, `sale_management`, `account_payment`.

OCA: `account_add_gln` (dependency of `edi_base`).
