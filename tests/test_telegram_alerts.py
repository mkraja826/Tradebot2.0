"""No-network Telegram relay tests; no Delta calls, orders, or real tokens."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
import sqlite3
import subprocess
import unittest
from unittest import mock

from tradebot.equity_monitor import MonitorStore
from tradebot.offhost_alerts import AlertRelayError, EVENT_DB
from tradebot.telegram_alerts import (
    TELEGRAM_CURSOR_DB, _message_for, deliver_once, initialize_baseline,
    inspect_outbox, main, telegram_send, valid_credentials,
)

TOKEN = "123456:" + "Z" * 35
CHAT = "12345678"


class TelegramAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="telegram-relay-test-")
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.store = MonitorStore(self.data / EVENT_DB)
        self.now = datetime(2026, 11, 22, 2, 0, tzinfo=timezone.utc)

    def _cursor(self):
        with closing(sqlite3.connect(self.data / TELEGRAM_CURSOR_DB)) as db:
            return db.execute(
                "SELECT last_event FROM delivery_cursor WHERE id=1"
            ).fetchone()[0]

    def test_credentials_reject_invalid_or_exfiltration_shapes(self):
        valid_credentials(TOKEN, CHAT)
        valid_credentials(TOKEN, "-1234567")
        for token, chat in (
            ("", CHAT), ("abc", CHAT), (TOKEN, ""),
            (TOKEN, "1;curl https://example.org"),
            ("123:short", CHAT), ("invalid/bot", CHAT)
        ):
            with self.subTest(token=bool(token), chat=chat):
                with self.assertRaises(AlertRelayError):
                    valid_credentials(token, chat)

    def test_check_is_read_only_and_does_not_create_cursor(self):
        self.store.publish(["missed_weekly_checkpoint"], at=self.now)
        with mock.patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": TOKEN,
                "TELEGRAM_CHAT_ID": CHAT}):
            with mock.patch(
                    "tradebot.telegram_alerts.telegram_send",
                    side_effect=AssertionError("NO NETWORK")):
                result = inspect_outbox(self.data)
                self.assertEqual(result, (1, 1))
                self.assertEqual(main(["--data-dir", str(self.data), "--check"]), 0)
        self.assertFalse((self.data / TELEGRAM_CURSOR_DB).exists())

    def test_baseline_explicitly_skips_old_incidents_and_records_active_count(self):
        self.store.publish(["missed_weekly_checkpoint"], at=self.now)
        state = initialize_baseline(self.data, TOKEN, CHAT)
        self.assertEqual(state["historical_events_skipped"], 1)
        self.assertEqual(state["currently_active_incident_count"], 1)
        self.assertFalse(state["telegram_delivery_commissioned"])
        self.assertEqual(self._cursor(), 1)
        with self.assertRaisesRegex(AlertRelayError,
                                    "telegram_baseline_already_exists"):
            initialize_baseline(self.data, TOKEN, CHAT)
        calls = []
        result = deliver_once(
            self.data, TOKEN, CHAT,
            send=lambda *args: calls.append(args))
        self.assertEqual(result["events_acked"], 0)
        self.assertEqual(calls, [])

    def test_new_incidents_are_sent_as_one_safe_digest_and_acked(self):
        initialize_baseline(self.data, TOKEN, CHAT)
        self.store.publish(["watchdog_heartbeat_stale",
                            "missed_daily_checkpoint"], at=self.now)
        calls = []
        result = deliver_once(
            self.data, TOKEN, CHAT,
            send=lambda *args: calls.append(args))
        self.assertEqual(result["events_acked"], 2)
        self.assertEqual(self._cursor(), 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], (TOKEN, CHAT))
        self.assertIn("watchdog_heartbeat_stale", calls[0][2])
        self.assertIn("missed_daily_checkpoint", calls[0][2])
        self.assertIn("Trading is NOT authorized", calls[0][2])
        self.assertNotIn("API_KEY", calls[0][2])
        self.assertEqual(deliver_once(
            self.data, TOKEN, CHAT,
            send=lambda *a: self.fail("duplicate delivery")
        )["events_acked"], 0)

    def test_failure_cannot_advance_ack_and_retries_identical_events(self):
        initialize_baseline(self.data, TOKEN, CHAT)
        self.store.publish(["equity_loss_limit_breached"], at=self.now)
        first = []
        def fail(*args):
            first.append(args[2])
            raise AlertRelayError("telegram_delivery_unavailable")
        with self.assertRaisesRegex(AlertRelayError,
                                    "telegram_delivery_unavailable"):
            deliver_once(self.data, TOKEN, CHAT, send=fail)
        self.assertEqual(self._cursor(), 0)
        retry = []
        deliver_once(
            self.data, TOKEN, CHAT,
            send=lambda *args: retry.append(args[2]))
        self.assertEqual(first, retry)
        self.assertEqual(self._cursor(), 1)

    def test_no_default_delivery_without_operator_baseline(self):
        self.store.publish(["missed_weekly_checkpoint"], at=self.now)
        self.assertFalse((self.data / TELEGRAM_CURSOR_DB).exists())
        with self.assertRaisesRegex(AlertRelayError,
                                    "telegram_baseline_required"):
            deliver_once(self.data, TOKEN, CHAT, send=lambda *a: None)
        self.assertFalse((self.data / TELEGRAM_CURSOR_DB).exists())

    def test_reject_unknown_incident_without_exposing_it(self):
        initialize_baseline(self.data, TOKEN, CHAT)
        with closing(sqlite3.connect(self.data / EVENT_DB)) as db:
            db.execute("INSERT INTO monitor_events(at_us,code,transition,severity) "
                       "VALUES(1,'API_KEY=SECRET','opened','critical')")
            db.commit()
        with self.assertRaisesRegex(AlertRelayError,
                                    "monitor_event_not_verified"):
            deliver_once(self.data, TOKEN, CHAT,
                         send=lambda *a: self.fail("unsafe delivery"))
        self.assertEqual(self._cursor(), 0)

    def test_telegram_network_ack_requires_intended_chat_id(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n):
                return json.dumps({"ok": True, "result": {
                    "chat": {"id": int(CHAT)}}}).encode()
        class FakeOpener:
            def open(self, req, timeout):
                self.req = req
                self.timeout = timeout
                return Response()
        opener = FakeOpener()
        with mock.patch("tradebot.telegram_alerts.request.build_opener",
                        return_value=opener):
            telegram_send(TOKEN, CHAT, "test only")
        self.assertEqual(opener.timeout, 8)
        self.assertIn("/sendMessage", opener.req.full_url)
        self.assertEqual(opener.req.get_method(), "POST")
        self.assertIn(b"chat_id=" + CHAT.encode(), opener.req.data)
        self.assertIn(b"text=test+only", opener.req.data)
        class WrongResponse(Response):
            def read(self, n):
                return b'{"ok":true,"result":{"chat":{"id":55555}}}'
        class WrongOpener(FakeOpener):
            def open(self, req, timeout):
                return WrongResponse()
        with mock.patch("tradebot.telegram_alerts.request.build_opener",
                        return_value=WrongOpener()):
            with self.assertRaisesRegex(AlertRelayError,
                                        "telegram_delivery_unacknowledged"):
                telegram_send(TOKEN, CHAT, "test")

    def test_test_message_uses_exact_monitor_file_without_creating_cursor(self):
        calls = []
        with mock.patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": TOKEN,
                "TELEGRAM_CHAT_ID": CHAT}):
            with mock.patch("tradebot.telegram_alerts.telegram_send",
                            side_effect=lambda *args: calls.append(args)):
                code = main(["--data-dir", str(self.data), "--test"])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("No trades placed", calls[0][-1])
        self.assertFalse((self.data / TELEGRAM_CURSOR_DB).exists())

    def test_scripts_only_stage_and_strip_exchange_credentials(self):
        root = Path(__file__).resolve().parents[1]
        for rel in ("ops/run_telegram_alerts.sh",
                    "ops/install_telegram_alerts_service.sh"):
            result = subprocess.run(
                ["bash", "-n", str(root / rel)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        launcher = (root / "ops/run_telegram_alerts.sh").read_text()
        installer = (root / "ops/install_telegram_alerts_service.sh").read_text()
        self.assertIn("telegram.env", launcher)
        self.assertIn('export PYTHONPATH="$PROJECT/src"', launcher)
        self.assertIn("unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET", launcher)
        self.assertIn("export ENABLE_DEMO_ORDERS=false", launcher)
        self.assertIn("export TRADEBOT_FIRE_DEMO_EXECUTION=false", launcher)
        self.assertIn("export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false", launcher)
        self.assertIn("--check", launcher)
        self.assertIn("systemctl daemon-reload", installer)
        self.assertNotIn("systemctl enable", installer)
        self.assertNotIn("systemctl restart", installer)
        self.assertNotIn("systemctl start", installer)


if __name__ == "__main__":
    unittest.main()
