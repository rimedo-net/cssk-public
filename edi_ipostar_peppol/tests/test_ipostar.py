# Copyright 2026 Rimedo, s.r.o.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import io
import json
from unittest.mock import patch
from xml.etree import ElementTree

from reportlab.pdfgen import canvas

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
