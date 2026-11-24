# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import io
import json
from datetime import date, timedelta
from unittest.mock import patch
from xml.etree import ElementTree

from reportlab.pdfgen import canvas

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.edi_base.exceptions import RetryableJobError

UBL = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
    "<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0</cbc:CustomizationID>"
    "<cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>"
    "<cbc:ID>%s</cbc:ID></Invoice>"
)

CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

TARGET = "odoo.addons.edi_ipostar_peppol.models.ipostar_connector.requests.request"


class FakeResponse:
    def __init__(self, status=200, body=None, content=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        if content is not None:
            self.content = content
        else:
            self.content = json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


@tagged("post_install", "-at_install")
class TestIpostar(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("ipostar.api_key", "ipk_test")
        cls.connector = cls.env["ipostar.connector"]

    def _out_msg(self, number="INV-1"):
        msg = self.env["edi.message"].create({
            "provider": "ipostar", "direction": "out", "name": number, "state": "queued",
        })
        msg._store_xml(UBL % number, filename="%s.xml" % number)
        return msg

    def test_send_ok_sandbox(self):
        msg = self._out_msg()
        calls = []

        def fake(method, url, **kw):
            calls.append((method, url, kw))
            return FakeResponse(201, {"id": 42, "status": "QUEUED", "sandbox": True})

        with patch(TARGET, side_effect=fake):
            self.connector._send_message(msg)
        method, url, kw = calls[0]
        self.assertEqual((method, url), ("POST", "https://ipostar.app/api/v1/invoices"))
        self.assertEqual(kw["headers"]["X-API-Key"], "ipk_test")
        self.assertEqual(kw["headers"]["Content-Type"], "application/xml")
        self.assertIn(b"<cbc:ID>INV-1</cbc:ID>", kw["data"])
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.provider_interchange_id, "42")
        self.assertTrue(msg.is_test_mode)

    def test_validation_failure_is_permanent_and_names_rules(self):
        msg = self._out_msg()
        body = {"error": "VALIDATION_FAILED", "issues": [
            {"ruleId": "SK-R-010", "flag": "warning", "message": "[SK-R-010] buyer VAT"},
            {"ruleId": "SK-R-011", "flag": "fatal", "message": "[SK-R-011] IBAN"},
        ]}
        with patch(TARGET, return_value=FakeResponse(422, body)):
            with self.assertRaises(UserError) as caught:
                self.connector._send_message(msg)
        text = str(caught.exception)
        self.assertIn("FATAL: [SK-R-011] IBAN", text)
        self.assertLess(text.index("SK-R-011"), text.index("SK-R-010"))
        self.assertEqual(text.count("[SK-R-011]"), 1)

    def test_rate_limit_and_no_credit_are_retryable(self):
        for status in (429, 402, 503):
            msg = self._out_msg("INV-%s" % status)
            with patch(TARGET, return_value=FakeResponse(status, {"error": "busy"})):
                with self.assertRaises(RetryableJobError):
                    self.connector._send_message(msg)

    def test_cron_send_keeps_retryable_queued(self):
        msg = self._out_msg()
        with patch(TARGET, return_value=FakeResponse(429, {"error": "queue_full"})):
            self.env["edi.message"]._cron_send_queued()
        self.assertEqual(msg.state, "queued")
        with patch(TARGET, return_value=FakeResponse(422, {"error": "VALIDATION_FAILED"})):
            self.env["edi.message"]._cron_send_queued()
        self.assertEqual(msg.state, "error")

    def test_status_mapping(self):
        cases = [
            ({"status": "SENDING"}, "sent"),
            ({"status": "SENT"}, "done"),
            ({"status": "FAILED", "error": "receiver unknown"}, "error"),
            ({"status": "SENT", "mls_status": "AB"}, "done"),
            ({"status": "SENT", "mls_status": "REJECTED", "mls_reason": "wrong PO"}, "error"),
        ]
        for i, (body, expected) in enumerate(cases):
            msg = self._out_msg("S-%s" % i)
            msg.write({"state": "sent", "provider_interchange_id": str(100 + i)})
            with patch(TARGET, return_value=FakeResponse(200, body)):
                self.connector._query_status(msg)
            self.assertEqual(msg.state, expected, body)
        self.assertIn("wrong PO", msg.error_message)

    def test_poll_skips_known_documents(self):
        self.env["edi.message"].create({
            "provider": "ipostar", "direction": "in", "name": "old",
            "state": "received", "provider_interchange_id": "7",
        })

        def fake(method, url, **kw):
            if url.endswith("/inbox"):
                self.assertIn("from", kw["params"])
                return FakeResponse(200, {"unread": 1, "count": 2, "documents": [{"id": 7}, {"id": 8, "invoice_ref": "FA-8"}]})
            self.assertTrue(url.endswith("/inbox/8/xml"), url)
            return FakeResponse(200, content=(UBL % "FA-8").encode())

        with patch(TARGET, side_effect=fake):
            result = self.connector._poll_inbound()
        self.assertEqual([m["raw_id"] for m in result["messages"]], ["8"])
        self.assertEqual(result["messages"][0]["external_id"], "FA-8")

    def test_oversized_document_is_refused(self):
        msg = self.env["edi.message"].create({
            "provider": "ipostar", "direction": "out", "name": "BIG", "state": "queued",
        })
        msg._store_xml((UBL % "BIG").replace("</Invoice>", "<!--%s--></Invoice>" % ("x" * 6 * 1024 * 1024)))
        with patch(TARGET) as request:
            with self.assertRaisesRegex(UserError, "5 MB"):
                self.connector._send_message(msg)
        request.assert_not_called()

    def test_embedded_pdf_is_sent_intact(self):
        # A real PDF, made here: in test mode Odoo renders reports as HTML.
        buf = io.BytesIO()
        pdf = canvas.Canvas(buf)
        pdf.drawString(72, 720, "Faktúra INV-PDF")
        pdf.save()
        raw = buf.getvalue()
        ref = (
            '<cac:AdditionalDocumentReference xmlns:cac="%s"><cbc:ID>INV-PDF.pdf</cbc:ID>'
            '<cac:Attachment><cbc:EmbeddedDocumentBinaryObject mimeCode="application/pdf" '
            'filename="INV-PDF.pdf">%s</cbc:EmbeddedDocumentBinaryObject></cac:Attachment>'
            "</cac:AdditionalDocumentReference></Invoice>"
        ) % (CAC_NS, base64.b64encode(raw).decode())
        msg = self.env["edi.message"].create({
            "provider": "ipostar", "direction": "out", "name": "INV-PDF", "state": "queued",
        })
        msg._store_xml((UBL % "INV-PDF").replace("</Invoice>", ref), filename="INV-PDF.xml")
        calls = []

        def fake(method, url, **kw):
            calls.append(kw["data"])
            return FakeResponse(201, {"id": 43, "status": "QUEUED", "sandbox": True})

        with patch(TARGET, side_effect=fake):
            self.connector._send_message(msg)
        self.assertEqual(msg.state, "sent")
        sent = ElementTree.fromstring(calls[0])
        binary = sent.find(".//{%s}EmbeddedDocumentBinaryObject" % CBC_NS)
        self.assertEqual(binary.get("mimeCode"), "application/pdf")
        self.assertEqual(base64.b64decode(binary.text), raw)
        self.assertTrue(raw.startswith(b"%PDF-"))

    def test_parse_envelope(self):
        self.assertEqual(self.connector._parse_envelope(UBL % "FA-9")["message_id"], "FA-9")
        self.assertEqual(self.connector._parse_envelope('<!DOCTYPE x [<!ENTITY a "b">]><x/>'), {})

    def test_missing_key(self):
        self.env["ir.config_parameter"].sudo().set_param("ipostar.api_key", "")
        with self.assertRaisesRegex(UserError, "API key"):
            self.connector._validate_config()
        self.assertEqual(self.connector._poll_inbound()["messages"], [])

    def test_peppol_provider_selection(self):
        move = self.env["account.move"]
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("peppol.transport", "ipostar")
        self.assertEqual(move._peppol_provider(), "ipostar")
        ICP.set_param("peppol.transport", "")
        self.assertTrue(move._peppol_provider())


@tagged("post_install", "-at_install")
class TestIpostarInboxPaging(TransactionCase):
    """H3: nothing received may be lost to an outage or a busy period."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.ICP.set_param("ipostar.api_key", "ipk_test")
        cls.ICP.set_param("ipostar.inbound.last_success", False)
        cls.connector = cls.env["ipostar.connector"]

    def _inbox(self, docs, fail_ids=()):
        """Fake API over ``docs`` = {id: date}; honours from/to/limit, with
        ``to`` exclusive. Records every listing call."""
        calls = []

        def fake(method, url, params=None, **kw):
            if url.endswith("/inbox"):
                calls.append(dict(params))
                since = date.fromisoformat(params["from"])
                until = date.fromisoformat(params["to"]) if "to" in params else None
                rows = [
                    {"id": doc_id} for doc_id, day in sorted(docs.items())
                    if day >= since and (until is None or day < until)
                ]
                return FakeResponse(200, {"documents": rows[:params["limit"]]})
            doc_id = url.split("/inbox/")[1].split("/")[0]
            if doc_id in fail_ids:
                return FakeResponse(503, {"error": "busy"})
            return FakeResponse(200, content=(UBL % ("FA-" + doc_id)).encode())

        return fake, calls

    def _poll(self, fake):
        state = {}
        with patch(TARGET, side_effect=fake):
            result = self.connector.with_context(
                ipostar_poll_state=state)._poll_inbound()
        return result, state

    def _store(self, result):
        """What edi_base does with the returned packages."""
        for pkg in result["messages"]:
            self.env["edi.message"].create({
                "provider": "ipostar", "direction": "in", "state": "received",
                "name": pkg["name"], "provider_interchange_id": pkg["raw_id"],
            })

    def _last_success(self):
        return self.ICP.get_param("ipostar.inbound.last_success")

    def test_first_poll_reads_the_look_back_and_sets_the_mark(self):
        today = fields.Date.context_today(self.connector)
        fake, calls = self._inbox({"1": today})
        result, state = self._poll(fake)
        self.assertEqual(calls[0]["from"], (today - timedelta(days=7)).isoformat())
        self._store(result)
        self.connector._finish_inbound_poll(state)
        self.assertTrue(self._last_success())
        self.assertIn("OK", self.ICP.get_param("ipostar.inbound.last_result"))

    def test_after_a_long_outage_it_reads_from_the_last_success(self):
        today = fields.Date.context_today(self.connector)
        last = fields.Datetime.now() - timedelta(days=30)
        self.ICP.set_param("ipostar.inbound.last_success",
                           fields.Datetime.to_string(last))
        old = today - timedelta(days=20)
        fake, calls = self._inbox({"5": old})
        result, state = self._poll(fake)
        self.assertEqual(calls[0]["from"], (last.date() - timedelta(days=1)).isoformat())
        self.assertEqual([m["raw_id"] for m in result["messages"]], ["5"],
                         "20 days old, outside the old 7-day window")

    def test_a_full_page_is_split_until_everything_is_listed(self):
        today = fields.Date.context_today(self.connector)
        docs = {}
        for n in range(450):  # 150 a day over three days
            docs[str(1000 + n)] = today - timedelta(days=n % 3)
        self.ICP.set_param("ipostar.inbound.lookback_days", 7)
        fake, calls = self._inbox(docs)
        result, state = self._poll(fake)
        self.assertGreater(len(calls), 1, "a full page must be split")
        self.assertTrue(state["truncated"], "450 new > 200 per run")
        self.assertTrue(result["has_more"])
        self.assertEqual(state["listed"], 450)
        self.assertEqual(len(result["messages"]), 200)
        self._store(result)
        self.connector._finish_inbound_poll(state)
        self.assertFalse(self._last_success(), "not everything fetched yet")
        # The re-triggered runs fetch the rest; then the mark moves.
        for _run in range(2):
            result, state = self._poll(fake)
            self._store(result)
            self.connector._finish_inbound_poll(state)
        self.assertEqual(
            self.env["edi.message"].search_count([
                ("provider", "=", "ipostar"), ("direction", "=", "in")]),
            450,
        )
        self.assertTrue(self._last_success())

    def test_a_download_failure_keeps_the_mark(self):
        today = fields.Date.context_today(self.connector)
        before = fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=3))
        self.ICP.set_param("ipostar.inbound.last_success", before)
        fake, _calls = self._inbox({"1": today, "2": today}, fail_ids=("2",))
        result, state = self._poll(fake)
        self.assertEqual([m["raw_id"] for m in result["messages"]], ["1"])
        self._store(result)
        self.connector._finish_inbound_poll(state)
        self.assertEqual(self._last_success(), before)
        self.assertIn("INCOMPLETE", self.ICP.get_param("ipostar.inbound.last_result"))

    def test_a_document_not_stored_keeps_the_mark(self):
        today = fields.Date.context_today(self.connector)
        fake, _calls = self._inbox({"1": today})
        result, state = self._poll(fake)
        self.connector._finish_inbound_poll(state)  # edi_base stored nothing
        self.assertFalse(self._last_success())

    def test_a_single_full_day_is_reported_incomplete(self):
        today = fields.Date.context_today(self.connector)
        fake, _calls = self._inbox({str(n): today for n in range(200)})
        self.ICP.set_param("ipostar.inbound.lookback_days", 1)
        result, state = self._poll(fake)
        self.assertFalse(state["complete"])
        self._store(result)
        self.connector._finish_inbound_poll(state)
        self.assertFalse(self._last_success())
        self.assertIn("INCOMPLETE", self.ICP.get_param("ipostar.inbound.last_result"))

    def test_a_listing_error_is_reported(self):
        def fake(method, url, **kw):
            return FakeResponse(500, {"error": "down"})

        result, state = self._poll(fake)
        self.assertEqual(result["messages"], [])
        self.connector._finish_inbound_poll(state)
        self.assertIn("listing failed", self.ICP.get_param("ipostar.inbound.last_result"))

    def test_settings_show_the_mark(self):
        self.ICP.set_param("ipostar.inbound.last_success", "2026-11-20 08:00:00")
        self.ICP.set_param("ipostar.inbound.last_result", "x UTC – OK")
        settings = self.env["res.config.settings"].create({})
        self.assertEqual(fields.Datetime.to_string(
            settings.ipostar_inbound_last_success), "2026-11-20 08:00:00")
        self.assertEqual(settings.ipostar_inbound_last_result, "x UTC – OK")
