# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "iPoštár EDI: Peppol BIS 3.0",
    "summary": "Send and receive Peppol BIS Billing 3.0 through the iPoštár "
    "access point (ipostar.app REST API)",
    "version": "18.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Rimedo, s.r.o.",
    "website": "https://rimedo.net",
    "license": "AGPL-3",
    "depends": ["edi_base_peppol"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "data/cron.xml",
        "views/res_config_settings.xml",
    ],
    "installable": True,
}
