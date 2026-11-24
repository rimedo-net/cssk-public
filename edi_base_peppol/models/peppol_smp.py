"""Provider-neutral Peppol participant lookup: SML (DNS) → SMP (HTTP).

Every Peppol participant is published by its access point's SMP (Service
Metadata Publisher), and the SML (Service Metadata Locator) points at that SMP
through DNS. Asking the network directly needs no account at any access point,
so the answer is the same whichever EDI provider this database sends through.

1. **SML.** The DNS name is
   ``base32(sha256(lower(participant)))`` without ``=`` padding, then
   ``.iso6523-actorid-upis.`` and the SML zone. It carries a U-NAPTR record,
   service ``Meta:SMP``, whose regexp names the SMP base URL. The old
   ``B-<md5>`` CNAME scheme and the European Commission zone
   (``edelivery.tech.ec.europa.eu``) are gone since OpenPeppol took the SML
   in-house in 2026; the zone is now ``participant.sml.prod.tech.peppol.org``
   (test network: ``participant.sml.test.tech.peppol.org``), overridable
   through the ``peppol.sml_zone`` system parameter.
2. **SMP.** ``GET <smp>/iso6523-actorid-upis::<participant>`` answers the
   ServiceGroup: one ``ServiceMetadataReference`` per document type the
   participant receives.

No DNS answer (NXDOMAIN) or an SMP 404 means the participant is not on the
network — an answer, not a failure. A resolver timeout or an SMP that does not
answer raises :class:`PeppolLookupError`: "could not check" must never read as
"not registered".

DNS goes through ``dnspython`` when it is installed (the system resolver).
The stock Odoo image does not ship it, so without it the NAPTR query goes over
DNS-over-HTTPS (JSON API, ``peppol.smp.doh_url``, Cloudflare by default). Only
the hashed participant id leaves the server that way.
"""

import base64
import hashlib
import logging
import shlex
from urllib.parse import quote, unquote

import requests
from lxml import etree

from odoo import _, api, models

try:
    import dns.exception
    import dns.resolver
except ImportError:  # pragma: no cover - depends on the image
    dns = None

_logger = logging.getLogger(__name__)

PARTICIPANT_SCHEME = "iso6523-actorid-upis"
SML_ZONE_PRODUCTION = "participant.sml.prod.tech.peppol.org"
SML_ZONE_TEST = "participant.sml.test.tech.peppol.org"
DEFAULT_DOH_URL = "https://cloudflare-dns.com/dns-query"
NAPTR_SERVICE = "meta:smp"
TIMEOUT = 15

DOC_INVOICE = (
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2::Invoice"
    "##urn:cen.eu:en16931:2017#compliant#"
    "urn:fdc:peppol.eu:2017:poacc:billing:3.0::2.1"
)
DOC_CREDIT_NOTE = (
    "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2::CreditNote"
    "##urn:cen.eu:en16931:2017#compliant#"
    "urn:fdc:peppol.eu:2017:poacc:billing:3.0::2.1"
)
DOC_INVOICE_RESPONSE = (
    "urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"
    "::ApplicationResponse##urn:fdc:peppol.eu:poacc:trns:invoice_response:3::2.1"
)

# Lookup states, also the values of res.partner.peppol_smp_state.
STATE_VALID = "valid"
STATE_NO_BILLING = "no_billing"
STATE_NOT_REGISTERED = "not_registered"


class PeppolLookupError(Exception):
    """The network could not be asked — not the same as "not registered"."""


class EdiPeppolSmp(models.AbstractModel):
    _name = "edi.peppol.smp"
    _description = "Peppol SML/SMP participant lookup"

    # ------------------------------------------------------------------
    # Participant identifiers
    # ------------------------------------------------------------------
    @api.model
    def _participant(self, eas, endpoint):
        """``eas:endpoint`` as the network spells it, or '' when incomplete."""
        eas = (eas or "").strip()
        endpoint = (endpoint or "").strip().replace(" ", "")
        if not eas or not endpoint:
            return ""
        return "%s:%s" % (eas, endpoint)

    @api.model
    def _sml_zone(self):
        ICP = self.env["ir.config_parameter"].sudo()
        return (ICP.get_param("peppol.sml_zone") or SML_ZONE_PRODUCTION).strip(".")

    @api.model
    def _sml_hostname(self, participant):
        digest = hashlib.sha256(participant.lower().encode()).digest()
        label = base64.b32encode(digest).decode().rstrip("=")
        return "%s.%s.%s" % (label, PARTICIPANT_SCHEME, self._sml_zone())

    # ------------------------------------------------------------------
    # SML: DNS NAPTR
    # ------------------------------------------------------------------
    @api.model
    def _naptr_records(self, hostname):
        """``[(order, preference, flags, service, regexp)]``; ``[]`` = no name.

        Raises PeppolLookupError when the resolver itself failed.
        """
        if dns is not None:
            return self._naptr_dnspython(hostname)
        return self._naptr_doh(hostname)

    @api.model
    def _naptr_dnspython(self, hostname):
        try:
            answer = dns.resolver.resolve(hostname, "NAPTR", lifetime=TIMEOUT)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except dns.exception.DNSException as e:
            raise PeppolLookupError(
                _("The Peppol SML (DNS) did not answer: %s", e)) from e
        return [
            (r.order, r.preference, r.flags.decode(), r.service.decode(),
             r.regexp.decode())
            for r in answer
        ]

    @api.model
    def _naptr_doh(self, hostname):
        ICP = self.env["ir.config_parameter"].sudo()
        url = ICP.get_param("peppol.smp.doh_url") or DEFAULT_DOH_URL
        try:
            response = requests.get(
                url, params={"name": hostname, "type": "NAPTR"},
                headers={"Accept": "application/dns-json"}, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            raise PeppolLookupError(
                _("The DNS-over-HTTPS resolver %(url)s did not answer: %(error)s",
                  url=url, error=e)) from e
        status = data.get("Status")
        if status == 3:  # NXDOMAIN
            return []
        if status != 0:
            raise PeppolLookupError(
                _("The DNS-over-HTTPS resolver answered with DNS status %s.",
                  status))
        records = []
        for answer in data.get("Answer") or []:
            if answer.get("type") != 35:  # NAPTR; CNAMEs may precede it
                continue
            # Cloudflare quotes the strings, Google does not; shlex reads both.
            try:
                order, pref, flags, service, regexp = shlex.split(
                    answer.get("data", ""))[:5]
                records.append((int(order), int(pref), flags, service, regexp))
            except ValueError:
                _logger.warning("Unreadable NAPTR answer %r", answer)
        return records

    @api.model
    def _smp_url_from_naptr(self, records):
        """The SMP base URL out of the ``U`` / ``Meta:SMP`` record, or ''."""
        candidates = sorted(
            r for r in records
            if r[2].upper() == "U" and r[3].lower() == NAPTR_SERVICE
        )
        for _order, _pref, _flags, _service, regexp in candidates:
            # "!^.*$!https://smp.example.com!" — the first character is the
            # delimiter; the replacement is the whole URL (no backreferences).
            if len(regexp) < 3:
                continue
            parts = regexp.split(regexp[0])
            if len(parts) >= 3 and parts[2].lower().startswith(("https://", "http://")):
                return parts[2].rstrip("/")
        return ""

    # ------------------------------------------------------------------
    # SMP: ServiceGroup
    # ------------------------------------------------------------------
    @api.model
    def _fetch_service_group(self, smp_url, participant):
        """ServiceGroup XML bytes, or ``None`` when the SMP does not know it."""
        url = "%s/%s" % (
            smp_url, quote("%s::%s" % (PARTICIPANT_SCHEME, participant), safe=""))
        try:
            response = requests.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise PeppolLookupError(
                _("The participant's SMP %(url)s did not answer: %(error)s",
                  url=smp_url, error=e)) from e
        if response.status_code == 404:
            return None
        if not response.ok:
            raise PeppolLookupError(
                _("The participant's SMP %(url)s answered HTTP %(status)s.",
                  url=smp_url, status=response.status_code))
        return response.content

    @api.model
    def _parse_service_group(self, content):
        """``(participant_id, [document type ids])`` out of a ServiceGroup."""
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            root = etree.fromstring(content, parser=parser)
        except etree.XMLSyntaxError as e:
            raise PeppolLookupError(
                _("The participant's SMP answered something that is not XML.")) from e
        participant = (root.findtext(".//{*}ParticipantIdentifier") or "").strip()
        doc_types = []
        for ref in root.iter("{*}ServiceMetadataReference"):
            href = unquote(ref.get("href") or "")
            _head, sep, tail = href.partition("/services/")
            if sep and tail:
                doc_types.append(tail)
        return participant, doc_types

    @staticmethod
    def _supports(doc_types, wanted):
        """Whether ``wanted`` (a bare document type id) is advertised.

        Entries carry their scheme: ``busdox-docid-qns::<id>`` must match
        exactly, ``peppol-doctype-wildcard::<prefix>*`` by prefix.
        """
        for entry in doc_types:
            scheme, sep, value = entry.partition("::")
            if not sep:
                scheme, value = "", entry
            if scheme == "peppol-doctype-wildcard" and value.endswith("*"):
                if wanted.startswith(value[:-1]):
                    return True
            elif value == wanted:
                return True
        return False

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def _lookup(self, participant):
        """Ask the Peppol network about ``participant`` (``eas:endpoint``).

        Returns a dict:

        * ``participant`` — the id asked about;
        * ``state`` — ``valid`` (registered, receives BIS3 invoices and
          credit notes), ``no_billing`` (registered, but not for those) or
          ``not_registered``;
        * ``smp_url`` — the SMP that publishes it ('' when not registered);
        * ``document_types`` — every advertised document type entry;
        * ``invoice``, ``credit_note``, ``invoice_response`` — booleans.

        Raises PeppolLookupError when the network could not be asked.
        """
        result = {
            "participant": participant, "state": STATE_NOT_REGISTERED,
            "smp_url": "", "document_types": [],
            "invoice": False, "credit_note": False, "invoice_response": False,
        }
        if not participant:
            return result
        records = self._naptr_records(self._sml_hostname(participant))
        smp_url = self._smp_url_from_naptr(records)
        if not smp_url:
            return result
        content = self._fetch_service_group(smp_url, participant)
        if content is None:
            return result
        found_id, doc_types = self._parse_service_group(content)
        # Identifiers are case-insensitive. Belgium pre-registers every
        # company on the Hermes SMP, which does not make it a real receiver.
        if found_id.lower() != participant.lower() or "hermes-belgium" in smp_url:
            return result
        result.update(
            smp_url=smp_url,
            document_types=doc_types,
            invoice=self._supports(doc_types, DOC_INVOICE),
            credit_note=self._supports(doc_types, DOC_CREDIT_NOTE),
            invoice_response=self._supports(doc_types, DOC_INVOICE_RESPONSE),
        )
        result["state"] = (
            STATE_VALID if result["invoice"] and result["credit_note"]
            else STATE_NO_BILLING
        )
        return result
