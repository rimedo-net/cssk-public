"""The contact's invoice delivery channel, with the e-invoice as one option.

Odoo's ``invoice_sending_method`` is the channel the Send & Print wizard uses.
It gains ``edi_peppol``: an e-invoice through the Peppol access point of an
installed EDI provider (GRiT, Editel, ePošťák). The key is not ``peppol``,
which Odoo's own ``account_peppol`` (Peppol through Odoo's IAP service) adds to
the same field; the two must never be confused, or one invoice could leave
through two access points.

An explicit choice on the contact wins (``account.move._peppol_route``).
Choosing email for a business the Slovak mandate covers is allowed, since
there are exceptions, but the contact says what it means.

**Check on Peppol** asks the network itself (``edi.peppol.smp``, SML → SMP)
whether the contact is registered and receives BIS3 invoices — no access
point account needed, so it is the same check whichever provider sends. The
answer is kept on the commercial partner together with the address it was
given for, so a changed address shows as unchecked again.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .peppol_smp import (
    STATE_NO_BILLING,
    STATE_NOT_REGISTERED,
    STATE_VALID,
    PeppolLookupError,
)

# Slovak schemes a VAT number can be spelled in: the DIČ (what most Slovak
# participants register under) and the IČ DPH.
EAS_SK_DIC = "0245"
EAS_SK_VAT = "9950"

SMP_STATES = [
    (STATE_VALID, "Receives e-invoices"),
    (STATE_NO_BILLING, "On Peppol, but not for BIS3 invoices"),
    (STATE_NOT_REGISTERED, "Not on Peppol"),
]


class ResPartner(models.Model):
    _inherit = "res.partner"

    invoice_sending_method = fields.Selection(
        selection_add=[("edi_peppol", "by e-invoice (Peppol)")],
    )
    peppol_sending_warning = fields.Char(compute="_compute_peppol_sending_warning")

    @api.depends_context("company")
    @api.depends("invoice_sending_method", "country_id", "is_company", "vat")
    def _compute_peppol_sending_warning(self):
        company = self.env.company.sudo()
        mandate = (company.peppol_send_enabled and company.peppol_scope == "sk_mandate"
                   and company.account_fiscal_country_id.code == "SK")
        for partner in self:
            commercial = partner.commercial_partner_id
            in_mandate = (mandate and commercial.country_id.code == "SK"
                          and (commercial.is_company or commercial.vat))
            method = partner.invoice_sending_method
            partner.peppol_sending_warning = _(
                "This customer is a Slovak business: from 1. 1. 2027 its invoices "
                "must be e-invoices, so sending them by email does not meet the "
                "mandate."
            ) if in_mandate and method and method != "edi_peppol" else False

    # -- network lookup (SML / SMP) --------------------------------------
    peppol_smp_state = fields.Selection(
        SMP_STATES, string="Peppol network check", readonly=True, copy=False,
        help="The answer the Peppol network gave the last time this contact "
        "was checked.")
    peppol_smp_participant = fields.Char(
        string="Checked Peppol address", readonly=True, copy=False)
    peppol_smp_checked_on = fields.Datetime(
        string="Checked on Peppol", readonly=True, copy=False)
    peppol_smp_status = fields.Selection(
        SMP_STATES,
        compute="_compute_peppol_smp_status",
        string="Peppol network status",
        help="The last network answer, shown only while it still describes "
        "the contact's current Peppol address.")

    @api.depends("peppol_eas", "peppol_endpoint", "commercial_partner_id",
                 "commercial_partner_id.peppol_smp_state",
                 "commercial_partner_id.peppol_smp_participant")
    def _compute_peppol_smp_status(self):
        smp = self.env["edi.peppol.smp"]
        for partner in self:
            commercial = partner.commercial_partner_id or partner
            current = smp._participant(commercial.peppol_eas, commercial.peppol_endpoint)
            checked = commercial.peppol_smp_participant or ""
            partner.peppol_smp_status = (
                commercial.peppol_smp_state
                if current and checked.lower() == current.lower() else False)

    def _peppol_vat_candidates(self):
        """Peppol addresses a Slovak contact may be registered under.

        Built from the VAT number (``SK`` + DIČ) or, for a non-VAT payer, the
        DIČ alone (``l10n_sk_dic`` when the SK localisation is installed).
        """
        self.ensure_one()
        vat = (self.vat or "").replace(" ", "").upper()
        dic = ""
        if vat.startswith("SK") and vat[2:].isdigit():
            dic = vat[2:]
        elif vat.isdigit() and (self.country_id.code or "SK") == "SK":
            dic = vat
        if not dic and "l10n_sk_dic" in self._fields:
            dic = (self.l10n_sk_dic or "").replace(" ", "")
        if not (dic.isdigit() and len(dic) == 10):
            return []
        candidates = [(EAS_SK_DIC, dic)]
        if vat.startswith("SK"):
            candidates.append((EAS_SK_VAT, "SK" + dic))
        return candidates

    def _peppol_smp_check(self):
        """Ask the network about this contact; returns the lookup result.

        The configured address is asked first. When it is missing, or not
        registered, the Slovak spellings of the VAT number are tried; a hit
        becomes the contact's Peppol address (and is logged), because the
        same DIČ cannot belong to anyone else.
        """
        self.ensure_one()
        partner = self.commercial_partner_id
        smp = self.env["edi.peppol.smp"]
        configured = (partner.peppol_eas, partner.peppol_endpoint)
        tried = []
        candidates = [configured] if all(configured) else []
        candidates += [c for c in partner._peppol_vat_candidates()
                       if c not in candidates]
        if not candidates:
            raise UserError(_(
                "%s has neither a Peppol address nor a Slovak VAT number / "
                "DIČ to look up. Set the Peppol e-address (EAS) and Peppol "
                "Endpoint first.", partner.display_name))

        result = None
        for eas, endpoint in candidates:
            participant = smp._participant(eas, endpoint)
            tried.append(participant)
            try:
                result = smp._lookup(participant)
            except PeppolLookupError as e:
                raise UserError(_(
                    "Could not check %(partner)s on the Peppol network:\n\n"
                    "%(error)s", partner=partner.display_name, error=e)) from e
            if result["state"] != STATE_NOT_REGISTERED:
                break
        result["tried"] = tried
        result["address_changed"] = False
        if result["state"] != STATE_NOT_REGISTERED and (eas, endpoint) != configured:
            partner.write({"peppol_eas": eas, "peppol_endpoint": endpoint})
            result["address_changed"] = True
            partner.message_post(body=_(
                "Peppol address set to %(new)s: the Peppol network has this "
                "contact registered under it (previously: %(old)s).",
                new=result["participant"],
                old=smp._participant(*configured) or _("none")))
        if result["state"] == STATE_NOT_REGISTERED:
            # Remember the answer for the address the contact actually has.
            result["participant"] = smp._participant(
                partner.peppol_eas, partner.peppol_endpoint) or tried[0]
        partner.write({
            "peppol_smp_state": result["state"],
            "peppol_smp_participant": result["participant"],
            "peppol_smp_checked_on": fields.Datetime.now(),
        })
        return result

    def action_peppol_smp_check(self):
        """Partner-form button: check this contact on the Peppol network."""
        self.ensure_one()
        result = self._peppol_smp_check()
        participant = result["participant"]
        state = result["state"]
        if state == STATE_VALID:
            kind, title = "success", _("Receives e-invoices on Peppol")
            message = _(
                "%(participant)s is registered on Peppol and receives BIS "
                "Billing 3.0 invoices and credit notes.", participant=participant)
            if not result["invoice_response"]:
                message += " " + _("It does not receive Invoice Responses.")
        elif state == STATE_NO_BILLING:
            kind, title = "warning", _("On Peppol, but not for BIS3 invoices")
            missing = [label for key, label in (
                ("invoice", _("invoices")), ("credit_note", _("credit notes")))
                if not result[key]]
            message = _(
                "%(participant)s is registered on Peppol but does not receive "
                "BIS Billing 3.0 %(missing)s, so sending them will be refused.",
                participant=participant, missing=_(" and ").join(missing))
        else:
            kind, title = "warning", _("Not on Peppol")
            message = _(
                "The Peppol network does not know %(tried)s, so Peppol cannot "
                "deliver to this contact. Either it has not registered yet, or "
                "it is registered under another address — ask for it.",
                tried=", ".join(result["tried"]))
        if result["address_changed"]:
            message += "\n\n" + _(
                "The contact's Peppol address was changed to %s.", participant)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": kind,
                "sticky": kind != "success",
                "title": title,
                "message": message,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
