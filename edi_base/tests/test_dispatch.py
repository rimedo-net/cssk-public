"""How a queued message leaves `queued`, when nothing is there to take it.

``edi_base`` no longer requires ``queue_job``. These tests hold that line: the
dispatch hooks do nothing on their own, the cron picks up only the providers
that asked for it, and — the one that matters — a provider dispatched by job is
never touched by the cron, because on a database carrying both a message picked
up twice is a document sent twice.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase

from odoo.addons.edi_base.exceptions import RetryableJobError


class DispatchCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Message = cls.env["edi.message"]
        # Two made-up providers, registered the way a connector module does it
        # in _register_hook. Real providers are not used: this is about the
        # registry, and borrowing one would tie the test to whatever else is
        # installed.
        cls.Message.PROVIDER_CONNECTOR_MAP["t_cron"] = "edi.connector.mixin"
        cls.Message.PROVIDER_CONNECTOR_MAP["t_queue"] = "edi.connector.mixin"
        cls.Message.PROVIDER_DISPATCH_MAP["t_cron"] = "cron"
        cls.Message.PROVIDER_DISPATCH_MAP["t_queue"] = "queue"
        cls.addClassCleanup(cls._forget_providers)

    @classmethod
    def _forget_providers(cls):
        for provider in ("t_cron", "t_queue"):
            cls.Message.PROVIDER_CONNECTOR_MAP.pop(provider, None)
            cls.Message.PROVIDER_DISPATCH_MAP.pop(provider, None)

    def _message(self, provider):
        return self.env["edi.message"].create({
            "provider": provider,
            "direction": "out",
            "state": "queued",
        })


class TestDispatchRegistry(DispatchCase):

    def test_an_unregistered_provider_still_means_a_queue(self):
        """Every provider was job-dispatched before the registry existed, so
        that is what silence has to keep meaning."""
        message = self._message("t_queue")
        self.Message.PROVIDER_DISPATCH_MAP.pop("t_queue")
        self.assertEqual(message._dispatch_mode(), "queue")
        self.Message.PROVIDER_DISPATCH_MAP["t_queue"] = "queue"

    def test_the_core_hook_does_nothing_by_itself(self):
        """With no job runner installed, handing over is somebody else's job —
        here, the cron. The message stays queued and no exception is raised."""
        message = self._message("t_cron")
        connector = self.env["edi.connector.mixin"]
        self.assertFalse(message._dispatch_send(connector))
        self.assertEqual(message.state, "queued")


class TestCronScope(DispatchCase):
    """The double-send guard."""

    def test_the_cron_sends_only_cron_registered_providers(self):
        cron_message = self._message("t_cron")
        queue_message = self._message("t_queue")
        sent = []

        def fake_send(self_, message):
            sent.append(message.id)
            return True

        with patch("odoo.addons.edi_base.models.edi_connector_mixin"
                   ".EdiConnectorMixin._send_message", fake_send, create=True):
            self.Message._cron_send_queued()

        self.assertIn(cron_message.id, sent)
        self.assertNotIn(
            queue_message.id, sent,
            "a job-dispatched message picked up by the cron is a document "
            "sent twice",
        )

    def test_a_retryable_failure_stays_queued(self):
        """The signal a job runner acts on, honoured the same way.

        Losing this would turn every rate limit and every timeout into a
        document a human has to re-send by hand.
        """
        message = self._message("t_cron")

        def fake_send(self_, record):
            raise RetryableJobError("the provider is busy")

        with patch("odoo.addons.edi_base.models.edi_connector_mixin"
                   ".EdiConnectorMixin._send_message", fake_send, create=True):
            self.Message._cron_send_queued()

        message.invalidate_recordset()
        self.assertEqual(message.state, "queued", "it must be tried again")
        self.assertEqual(message.blocking_level, "warning")

    def test_a_permanent_failure_becomes_an_error(self):
        message = self._message("t_cron")

        def fake_send(self_, record):
            raise ValueError("this document will never be accepted")

        with patch("odoo.addons.edi_base.models.edi_connector_mixin"
                   ".EdiConnectorMixin._send_message", fake_send, create=True):
            self.Message._cron_send_queued()

        message.invalidate_recordset()
        self.assertEqual(message.state, "error")
        self.assertIn("never be accepted", message.error_message)


class TestCronSendDurability(DispatchCase):
    """A run cut off half-way must not send its documents a second time."""

    PATCH = ("odoo.addons.edi_base.models.edi_connector_mixin"
             ".EdiConnectorMixin._send_message")

    def test_the_message_is_sending_while_it_leaves(self):
        message = self._message("t_cron")
        seen = []

        def fake_send(self_, record):
            seen.append((record.state, bool(record.send_started_at)))
            record.write({"state": "sent"})
            return True

        with patch(self.PATCH, fake_send, create=True):
            self.Message._cron_send_queued()

        self.assertEqual(seen, [("sending", True)])
        message.invalidate_recordset()
        self.assertEqual(message.state, "sent")
        self.assertFalse(message.send_started_at, "outcome known: cleared")

    def test_a_retryable_failure_clears_the_claim(self):
        message = self._message("t_cron")

        def fake_send(self_, record):
            raise RetryableJobError("busy")

        with patch(self.PATCH, fake_send, create=True):
            self.Message._cron_send_queued()

        message.invalidate_recordset()
        self.assertEqual(message.state, "queued")
        self.assertFalse(message.send_started_at)

    def test_a_message_already_sending_is_not_sent_again(self):
        """What a crashed run leaves behind is never picked up as queued."""
        message = self._message("t_cron")
        message.write({"state": "sending",
                       "send_started_at": fields.Datetime.now()})
        sent = []

        def fake_send(self_, record):
            sent.append(record.id)
            return True

        with patch(self.PATCH, fake_send, create=True):
            self.Message._cron_send_queued()

        self.assertEqual(sent, [])
        self.assertEqual(message.state, "sending", "not stale yet")

    def test_an_interrupted_send_goes_to_a_human(self):
        message = self._message("t_cron")
        started = fields.Datetime.now() - timedelta(
            minutes=self.Message.SENDING_STALE_MINUTES + 1)
        message.write({"state": "sending", "send_started_at": started})
        sent = []

        def fake_send(self_, record):
            sent.append(record.id)
            return True

        with patch(self.PATCH, fake_send, create=True):
            self.Message._cron_send_queued()

        message.invalidate_recordset()
        self.assertEqual(sent, [], "outcome unknown: never re-sent by itself")
        self.assertEqual(message.state, "error")
        self.assertEqual(message.send_started_at, started,
                         "kept, so the document stays locked")
        self.assertIn("do NOT send it again", message.error_message)

    def test_send_clears_the_unknown_outcome(self):
        """Someone checked the portal and sends again on purpose."""
        message = self._message("t_cron")
        message.write({"state": "error",
                       "send_started_at": fields.Datetime.now()})
        message.action_send()
        self.assertEqual(message.state, "queued")
        self.assertFalse(message.send_started_at)


class TestExceptionShim(TransactionCase):

    def test_the_real_queue_job_classes_are_used_when_present(self):
        """Re-exported, never shadowed.

        A runner recognises its own exception classes by identity. A look-alike
        defined here would be caught by nothing and retried never — so if
        queue_job is installed, these must BE its classes.
        """
        try:
            from odoo.addons.queue_job.exception import (
                RetryableJobError as TheirRetryable,
            )
        except ImportError:
            self.skipTest("queue_job is not installed in this run")
        self.assertIs(RetryableJobError, TheirRetryable)
