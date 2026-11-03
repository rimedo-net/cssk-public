# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ipostar_api_key = fields.Char(
        string="iPoštár API Key",
        config_parameter="ipostar.api_key",
        help="X-API-Key from the iPoštár customer zone (starts with ipk_).",
    )
    ipostar_base_url = fields.Char(
        string="iPoštár API URL",
        config_parameter="ipostar.base_url",
        default="https://ipostar.app/api/v1",
    )
    ipostar_lookback_days = fields.Integer(
        string="Inbox look-back (days)",
        config_parameter="ipostar.inbound.lookback_days",
        default=7,
        help="Each inbound poll re-reads this many days of the iPoštár inbox "
        "and skips documents already stored.",
    )
    # Same definition as edi_epostak_peppol, so either module can show it.
    peppol_transport = fields.Selection(
        selection="_selection_peppol_transport",
        string="Peppol Transport",
        config_parameter="peppol.transport",
        help="Which installed EDI provider carries Peppol documents.",
    )

    @api.model
    def _selection_peppol_transport(self):
        return self.env["edi.message"]._selection_provider()

    def action_ipostar_test_connection(self):
        self.execute()
        account = self.env["ipostar.connector"]._authenticate()
        raise UserError(
            _("iPoštár connection OK.\n\n%s",
              "\n".join("%s: %s" % kv for kv in sorted(account.items())
                        if not isinstance(kv[1], (dict, list))))
        )
