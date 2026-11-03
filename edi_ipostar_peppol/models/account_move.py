# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""iPoštár as a Peppol transport for edi_base_peppol.

With several transports installed (ePošťák too) the ``peppol.transport``
setting picks one. iPoštár claims Peppol when it is chosen there, or when the
setting is empty and no other transport claims it.
"""

from odoo import models

from .ipostar_connector import PROVIDER


class AccountMove(models.Model):
    _inherit = "account.move"

    def _peppol_provider(self):
        chosen = self.env["ir.config_parameter"].sudo().get_param("peppol.transport", "")
        if chosen == PROVIDER:
            return PROVIDER
        provider = super()._peppol_provider()
        if not provider and not chosen:
            return PROVIDER
        return provider

    def _peppol_send(self, msg):
        self.ensure_one()
        if msg.provider != PROVIDER:
            return super()._peppol_send(msg)
        return msg._enqueue_send(self.env["ipostar.connector"])
