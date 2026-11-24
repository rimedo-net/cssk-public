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
        string="First poll look-back (days)",
        config_parameter="ipostar.inbound.lookback_days",
        default=7,
        help="How far back the very first poll reads the iPoštár inbox, or any "
        "poll after \"Last successful poll\" has been cleared. Later polls "
        "read from the last successful poll.",
    )
    ipostar_inbound_last_success = fields.Datetime(
        string="Last successful poll",
        config_parameter="ipostar.inbound.last_success",
        help="When a poll last saw the whole inbox and stored every new "
        "document. The next poll reads from one day before this, however long "
        "ago it was, so an outage loses nothing. Set it earlier to read an "
        "older period again; documents already in Odoo are skipped.",
    )
    ipostar_inbound_last_result = fields.Char(
        string="Last poll",
        compute="_compute_ipostar_inbound_last_result",
        help="Outcome of the most recent inbound poll. INCOMPLETE means some "
        "documents were not stored; the same period is read again next time.",
    )
    # Same definition as edi_epostak_peppol, so either module can show it.
    peppol_transport = fields.Selection(
        selection="_selection_peppol_transport",
        string="Peppol Transport",
        config_parameter="peppol.transport",
        help="Which installed EDI provider carries Peppol documents.",
    )

    def _compute_ipostar_inbound_last_result(self):
        # Not a config_parameter field: saving the settings would write the
        # value loaded with the form back over a newer one.
        value = self.env["ir.config_parameter"].sudo().get_param(
            "ipostar.inbound.last_result") or False
        for settings in self:
            settings.ipostar_inbound_last_result = value

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
