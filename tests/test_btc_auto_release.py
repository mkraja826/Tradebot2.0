"""Regression tests for narrowly scoped BTC demo no-order halt release."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tradebot.btc_auto_review import acknowledge, APPROVAL
from tradebot.btc_auto_release import RELEASE_APPROVAL, release_reviewed_no_order_halt

PRESS = "7ed4f24a350d422c9df35045f3be4ede"


class HaltReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.timestamp = datetime.now(timezone.utc)
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.executescript("""
                CREATE TABLE fire_requests(
                    press TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
                    status TEXT, result TEXT);
                CREATE TABLE fire_entries(press TEXT);
            """)
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?,?)",(
                PRESS, self.timestamp.isoformat(), self.timestamp.isoformat(),
                "rejected_no_order", json.dumps({
                    "reason_code": "model_decision_failed",
                    "orders_submitted": False, "protection_verified": False})))
        with sqlite3.connect(self.root / "btc-auto-demo.sqlite") as db:
            db.execute("""CREATE TABLE btc_auto_attempts(
                attempt_id TEXT PRIMARY KEY, utc_day TEXT NOT NULL,
                requested_at INTEGER NOT NULL, status TEXT NOT NULL)""")
            db.execute("INSERT INTO btc_auto_attempts VALUES(?,?,?,?)",(
                PRESS, self.timestamp.date().isoformat(),
                int(self.timestamp.timestamp()) - 2, "rejected_no_order"))
        halt = self.root / "btc-auto-demo-halt"
        halt.touch()
        halt.chmod(0o600)
        os.utime(halt, (self.timestamp.timestamp(), self.timestamp.timestamp()))
        self.halt = halt
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)

    def release(self, **kwargs):
        return release_reviewed_no_order_halt(
            self.root, approval=kwargs.pop("approval", RELEASE_APPROVAL),
            candidate=kwargs.pop("candidate", lambda root: True),
            stopped=kwargs.pop("stopped", lambda: True),
            armed=kwargs.pop("armed", lambda: True), **kwargs)

    def test_exact_reviewed_no_order_can_release_and_audits(self):
        output = self.release()
        self.assertEqual(output["status"], "reviewed_no_order_halt_released")
        self.assertFalse(output["trade_authorized"])
        self.assertFalse(output["broker_mutations"])
        self.assertFalse(self.halt.exists())
        audit = self.root / ("btc-auto-halt-release-" + PRESS + ".json")
        self.assertEqual(audit.stat().st_mode & 0o777, 0o600)
        payload = json.loads(audit.read_text())
        self.assertEqual(payload["press"], PRESS)
        self.assertEqual(len(payload["receipt_sha256"]), 64)
        self.assertTrue((self.root / "btc-auto-reviewed-no-order.json").exists())
        with self.assertRaisesRegex(ValueError, "No halt"):
            self.release()

    def test_refuse_no_approval_unsafe_worker_arming_or_broker(self):
        for kwargs in (
            {"approval": "no"},
            {"candidate": lambda root: False},
            {"stopped": lambda: False},
            {"armed": lambda: False},
        ):
            with self.subTest(keys=tuple(kwargs)):
                with self.assertRaises(ValueError):
                    self.release(**kwargs)
                self.assertTrue(self.halt.exists())
                self.assertFalse(list(self.root.glob("btc-auto-halt-release-*.json")))

    def test_refuse_halt_not_from_same_exact_failure(self):
        old = self.timestamp - timedelta(seconds=100)
        os.utime(self.halt, (old.timestamp(), old.timestamp()))
        with self.assertRaisesRegex(ValueError, "time-bound"):
            self.release()
        self.assertTrue(self.halt.exists())

    def test_refuse_attempt_mismatch_and_unverified_broker_intent(self):
        with sqlite3.connect(self.root / "btc-auto-demo.sqlite") as db:
            db.execute("UPDATE btc_auto_attempts SET status='unverified_execution_error'")
        with self.assertRaisesRegex(ValueError, "no-order attempt"):
            self.release()
        with sqlite3.connect(self.root / "btc-auto-demo.sqlite") as db:
            db.execute("UPDATE btc_auto_attempts SET status='rejected_no_order'")
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("INSERT INTO fire_entries VALUES(?)", (PRESS,))
        with self.assertRaisesRegex(ValueError, "no-order attempt"):
            self.release()
        self.assertTrue(self.halt.exists())

    def test_refuse_untrusted_halt_permissions(self):
        self.halt.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "untrusted halt"):
            self.release()
        self.assertTrue(self.halt.exists())
        self.assertFalse(list(self.root.glob("btc-auto-halt-release-*.json")))


if __name__ == "__main__":
    unittest.main()
