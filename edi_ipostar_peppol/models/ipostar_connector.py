# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""iPoštár connector — the ``edi.connector.mixin`` transport for ipostar.app.

REST API (https://ipostar.app/vyvojari), authenticated by ``X-API-Key: ipk_…``:

* ``POST /invoices`` — raw UBL 2.1 Invoice/CreditNote (Peppol BIS 3.0) as
  ``application/xml``; iPoštár validates (XSD + Schematron incl. SK CIUS) and
  answers ``id`` + ``status``. 422 ``VALIDATION_FAILED`` lists ``issues``.
* ``GET /invoices/{id}`` — ``QUEUED → SENDING → SENT`` or ``FAILED``;
  ``SENT`` means the receiver's access point took it. ``mls`` carries the
  Message Level Status (``ACCEPTED`` / ``REJECTED`` + ``mls_reason``).
* ``GET /inbox`` + ``GET /inbox/{id}/xml`` — received documents.

There is no separate sandbox URL: a new iPoštár account *is* in sandbox until
switched over, and every send answer says so (``sandbox``). That flag is
stamped on the message so test traffic is badged as such.

Inbound has no acknowledge call. ``newForKey`` would mark a document read the
moment it is listed — before Odoo has stored it — so it is deliberately not
used. Instead every poll re-reads a look-back window and skips ids already
stored; a document whose import failed is simply picked up again.
"""

import datetime
import logging
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.edi_base.exceptions import RetryableJobError

_logger = logging.getLogger(__name__)

PROVIDER = "ipostar"
SANDBOX = "sandbox"
PRODUCTION = "production"

CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

DEFAULT_BASE_URL = "https://ipostar.app/api/v1"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_INBOX_LIMIT = 200
TIMEOUT = 60
# iPoštár validates documents up to 5 MB; embedded attachments are base64,
# a third larger than the files themselves.
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

# Statuses of GET /invoices/{id}
STATUS_PENDING = {"QUEUED", "SENDING", "ISSUED"}
STATUS_DONE = {"SENT"}
STATUS_ERROR = {"FAILED"}

# 402 (no credit) is fixed by a top-up, 429/503 by waiting: keep the message
# queued instead of turning it into an error someone has to re-send by hand.
RETRYABLE_STATUS = {402, 408, 429, 500, 502, 503, 504}


class IpostarApiError(Exception):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self):
        return self.status is None or self.status in RETRYABLE_STATUS


class IpostarConnector(models.TransientModel):
    _name = "ipostar.connector"
    _inherit = ["edi.connector.mixin"]
    _description = "iPoštár Connector"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _get_config(self):
        ICP = self.env["ir.config_parameter"].sudo()
        return {
            "base_url": (ICP.get_param("ipostar.base_url") or DEFAULT_BASE_URL).rstrip("/"),
            "api_key": (ICP.get_param("ipostar.api_key") or "").strip(),
            "lookback_days": int(
                ICP.get_param("ipostar.inbound.lookback_days") or DEFAULT_LOOKBACK_DAYS
            ),
        }

    def _validate_config(self):
        cfg = self._get_config()
        if not cfg["api_key"]:
            raise UserError(
                _(
                    "The iPoštár API key is not set. Generate one in the iPoštár "
                    "customer zone and enter it in Settings → EDI → iPoštár."
                )
            )
        if not cfg["base_url"].startswith("https://"):
            # iPoštár answers plain http with 403 https_required.
            raise UserError(_("The iPoštár API URL must use https://."))
        return cfg

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    @staticmethod
    def _error_text(response):
        try:
            data = response.json()
        except ValueError:
            return (response.text or "")[:500]
        if not isinstance(data, dict):
            return str(data)[:500]
        parts = [str(data.get(k)) for k in ("error", "code", "message") if data.get(k)]
        # Fatal rules first: they are why the document was refused; warnings
        # are listed after them for whoever fixes the partner/invoice anyway.
        issues = sorted(
            data.get("issues") or [],
            key=lambda i: (i.get("flag") or "") != "fatal",
        )
        for issue in issues:
            message = issue.get("message") or ""
            rule = issue.get("ruleId") or ""
            if rule and rule not in message:
                message = "[%s] %s" % (rule, message)
            parts.append("%s: %s" % ((issue.get("flag") or "?").upper(), message))
        return "\n".join(parts) or (response.text or "")[:500]

    def _request(self, cfg, method, path, data=None, params=None,
                 content_type=None, expected=(200,), raw=False):
        headers = {"X-API-Key": cfg["api_key"], "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        url = "%s%s" % (cfg["base_url"], path)
        try:
            response = requests.request(
                method, url, headers=headers, data=data, params=params,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise IpostarApiError(_("iPoštár is not reachable: %s", e)) from e
        if response.status_code not in expected:
            retry_after = response.headers.get("Retry-After")
            raise IpostarApiError(
                _(
                    "iPoštár %(method)s %(path)s → HTTP %(status)s: %(detail)s",
                    method=method,
                    path=path,
                    status=response.status_code,
                    detail=self._error_text(response),
                ),
                status=response.status_code,
                retry_after=int(retry_after) if (retry_after or "").isdigit() else None,
            )
        if raw:
            return response
        try:
            return response.json() if response.content else {}
        except ValueError:
            return {}

    def _parse_envelope(self, raw):
        """Envelope fields edi_base reads from the connector: the UBL cbc:ID
        (message id / inbound dedup). Refuses DTDs like edi_base_peppol."""
        raw = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
        head = raw[:8192].lower()
        if not raw or b"<!doctype" in head or b"<!entity" in head:
            return {}
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            return {}
        el = root.find("{%s}ID" % CBC_NS)
        return {"message_id": (el.text or "").strip() if el is not None else ""}

    def _authenticate(self):
        """Test the key: GET /account."""
        cfg = self._validate_config()
        return self._request(cfg, "GET", "/account")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def _send_message(self, message_record):
        for msg in message_record:
            self._send_one(msg)
        return True

    def _send_one(self, msg):
        cfg = self._validate_config()
        xml_content = msg._get_xml_content()
        if not xml_content:
            raise UserError(
                _("EDI message %s has no XML payload to send.", msg.display_name)
            )
        payload = xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise UserError(_(
                "%(name)s is %(size).1f MB; iPoštár accepts at most 5 MB per "
                "e-invoice. Attach fewer or smaller files (attachments travel "
                "inside the document, base64 encoded).",
                name=msg.display_name, size=len(payload) / 1024 / 1024,
            ))
        try:
            data = self._request(
                cfg, "POST", "/invoices", data=payload,
                content_type="application/xml", expected=(200, 201, 202),
            )
        except IpostarApiError as e:
            if e.retryable:
                # Leaves the message queued; edi_base's cron tries again.
                raise RetryableJobError(str(e)) from e
            # Permanent (400/401/403/422): edi_base marks the message error
            # with this text, which names the failing Schematron rules.
            raise UserError(str(e)) from e

        vals = {
            "state": "sent",
            "blocking_level": False,
            "error_message": False,
            "provider_interchange_id": str(data.get("id") or "") or False,
            "provider_mode": SANDBOX if data.get("sandbox") else PRODUCTION,
        }
        warnings = data.get("warnings") or []
        if warnings:
            vals["blocking_level"] = "warning"
            vals["error_message"] = "\n".join(
                w.get("message", str(w)) if isinstance(w, dict) else str(w)
                for w in warnings
            )
        msg.write(vals)
        _logger.info(
            "iPoštár accepted %s as %s (status %s, %s)",
            msg.name, data.get("id"), data.get("status"), vals["provider_mode"],
        )
        # A status the intake already answered terminally is applied at once.
        self._apply_status(msg, data)
        return True

    # ------------------------------------------------------------------
    # Outbound delivery status (cron)
    # ------------------------------------------------------------------

    def _query_status(self, message_records=None):
        if message_records is None:
            message_records = self.env["edi.message"].search(
                [
                    ("provider", "=", PROVIDER),
                    ("direction", "=", "out"),
                    ("state", "=", "sent"),
                    ("provider_interchange_id", "!=", False),
                ],
                limit=500,
            )
        if not message_records:
            return
        try:
            cfg = self._validate_config()
        except UserError as e:
            _logger.warning("iPoštár status query skipped: %s", e)
            return
        for msg in message_records:
            try:
                data = self._request(
                    cfg, "GET",
                    "/invoices/%s" % quote(str(msg.provider_interchange_id), safe=""),
                )
            except IpostarApiError as e:
                if e.status == 401:
                    _logger.warning("iPoštár status query refused: %s", e)
                    return
                _logger.info("iPoštár status query failed for %s: %s", msg.name, e)
                continue
            self._apply_status(msg, data)

    def _apply_status(self, msg, data):
        status = str(data.get("status") or "").strip().upper()
        # Live API: ``mls_status`` (ACCEPTED / REJECTED / AB in sandbox).
        mls = str(data.get("mls_status") or data.get("mls") or "").strip().upper()
        if mls == "REJECTED":
            msg.write({
                "state": "error",
                "blocking_level": "error",
                "error_message": _(
                    "Rejected by the receiver (MLS): %s",
                    data.get("mls_reason") or "-",
                ),
            })
        elif status in STATUS_ERROR:
            msg.write({
                "state": "error",
                "blocking_level": "error",
                "error_message": _(
                    "iPoštár status %(status)s: %(error)s",
                    status=status,
                    error=data.get("error") or "-",
                ),
            })
        elif status in STATUS_DONE:
            msg.write({"state": "done"})
        # QUEUED / SENDING / anything unknown → stays 'sent'.

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    @staticmethod
    def _inbox_items(listing):
        if isinstance(listing, list):
            return listing
        for key in ("items", "documents", "data", "inbox", "results"):
            if isinstance(listing.get(key), list):
                return listing[key]
        return []

    def _poll_inbound(self):
        try:
            cfg = self._validate_config()
        except UserError as e:
            _logger.error("iPoštár inbound poll skipped, not configured: %s", e)
            return {"messages": [], "has_more": False}

        since = datetime.date.today() - datetime.timedelta(days=cfg["lookback_days"])
        try:
            listing = self._request(
                cfg, "GET", "/inbox",
                params={"from": since.isoformat(), "limit": DEFAULT_INBOX_LIMIT},
            )
        except IpostarApiError as e:
            _logger.error("iPoštár inbox listing failed: %s", e)
            return {"messages": [], "has_more": False}

        items = self._inbox_items(listing)
        ids = [str(item.get("id")) for item in items if item.get("id")]
        known = set(
            self.env["edi.message"].search([
                ("provider", "=", PROVIDER),
                ("direction", "=", "in"),
                ("provider_interchange_id", "in", ids),
            ]).mapped("provider_interchange_id")
        )
        messages = []
        for item in items:
            doc_id = str(item.get("id") or "")
            if not doc_id or doc_id in known:
                continue
            try:
                response = self._request(
                    cfg, "GET", "/inbox/%s/xml" % quote(doc_id, safe=""),
                    raw=True,
                )
            except IpostarApiError as e:
                # Not stored → reappears on the next poll inside the window.
                _logger.error("iPoštár: could not fetch inbox %s: %s", doc_id, e)
                continue
            if not response.content:
                continue
            messages.append({
                "name": "ipostar_%s.xml" % doc_id,
                "xml_content": response.content.decode("utf-8"),
                "raw_id": doc_id,
                "external_id": (
                    item.get("invoice_ref") or item.get("invoiceRef") or doc_id
                ),
            })
        _logger.info(
            "iPoštár inbox: %s listed, %s new since %s", len(items), len(messages), since
        )
        # A full page may hide more: let edi_base re-trigger the cron.
        return {"messages": messages, "has_more": len(items) >= DEFAULT_INBOX_LIMIT and bool(messages)}

    def _acknowledge_inbound(self, raw_id):
        # iPoštár has no acknowledge endpoint; dedup is by provider_interchange_id.
        return True
