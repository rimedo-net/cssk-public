# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models

from .ipostar_connector import PROVIDER, SANDBOX


class EdiMessage(models.Model):
    _inherit = "edi.message"

    @api.model
    def _selection_provider(self):
        return super()._selection_provider() + [(PROVIDER, "iPoštár")]

    def _register_hook(self):
        super()._register_hook()
        self.PROVIDER_CONNECTOR_MAP[PROVIDER] = "ipostar.connector"
        self.PROVIDER_CRON_MAP[PROVIDER] = "edi_ipostar_peppol.cron_ipostar_get_messages"
        # No job runner needed: edi_base's own cron sends what is queued.
        self.PROVIDER_DISPATCH_MAP[PROVIDER] = "cron"

    def _compute_is_test_mode(self):
        super()._compute_is_test_mode()
        for rec in self.filtered(lambda r: r.provider == PROVIDER):
            rec.is_test_mode = rec.provider_mode == SANDBOX
