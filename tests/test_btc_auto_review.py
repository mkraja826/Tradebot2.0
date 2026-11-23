"""Offline evidence-only tests for historical BTC FIRE model-failure review."""
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradebot.btc_auto_review import (
    APPROVAL, MARKER_NAME, acknowledge, evidence, reviewed_receipt_matches,
)
from tradebot.btc_autonomous_demo import prior_fire_receipts_safe

PRESS = "52531d80d1e3467f9e5507052b19a4f2"


class NoOrderReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / "fire-ops.sqlite"
        with sqlite3.connect(self.dbpath) as db:
            db.executescript("""CREATE TABLE fire_requests(
                press TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
                status TEXT, result TEXT);
                CREATE TABLE fire_entries(press TEXT);""")
        self.insert(PRESS)

    def insert(self, press, *, reason="model_decision_failed",
               submitted=False, status="rejected_no_order"):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?,?)",
                       (press, press, press, status, json.dumps({
                           "reason_code": reason,
                           "orders_submitted": submitted,
                           "protection_verified": False})))

    def test_operator_acknowledgement_requires_exact_consent_and_broker(self):
        self.assertIsNotNone(evidence(self.root))
        self.assertFalse(prior_fire_receipts_safe(self.root))
        with self.assertRaises(ValueError):
            acknowledge(self.root, approval="not approved",
                        candidate=lambda root: self.fail("broker called"))
        with self.assertRaises(ValueError):
            acknowledge(self.root, approval=APPROVAL,
                        candidate=lambda root: False)
        self.assertFalse((self.root / MARKER_NAME).exists())
        report = acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.assertEqual(report["status"], "reviewed_no_order")
        self.assertFalse(report["broker_mutations"])
        self.assertTrue(reviewed_receipt_matches(self.root))
        self.assertTrue(prior_fire_receipts_safe(self.root))

    def test_marker_bound_to_exact_last_receipt(self):
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.insert("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertFalse(reviewed_receipt_matches(self.root))
        self.assertFalse(prior_fire_receipts_safe(self.root))

    def test_review_rejects_any_order_intent_even_with_false_receipt_flag(self):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("INSERT INTO fire_entries VALUES(?)", (PRESS,))
        self.assertIsNone(evidence(self.root))
        with self.assertRaises(ValueError):
            acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)

    def test_review_rejects_order_or_non_model_receipts(self):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("UPDATE fire_requests SET result=?",
                       (json.dumps({"reason_code": "model_decision_failed",
                                    "orders_submitted": True}),))
        self.assertIsNone(evidence(self.root))
        with sqlite3.connect(self.dbpath) as db:
            db.execute("UPDATE fire_requests SET result=?",
                       (json.dumps({"reason_code": "gpt6_wait_no_trade",
                                    "orders_submitted": False}),))
        self.assertIsNone(evidence(self.root))

    def test_wrong_permissions_and_symlinks_never_verify_review(self):
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        path = self.root / MARKER_NAME
        path.chmod(0o644)
        self.assertFalse(reviewed_receipt_matches(self.root))
        path.chmod(0o600)
        data = path.read_bytes()
        path.unlink()
        other = self.root / "outside"
        other.write_bytes(data)
        other.chmod(0o600)
        path.symlink_to(other)
        self.assertFalse(reviewed_receipt_matches(self.root))

    def test_a_fake_marker_cannot_approve_without_evidence(self):
        marker = self.root / MARKER_NAME
        marker.write_text(json.dumps({"status": "approved"}))
        marker.chmod(0o600)
        self.assertFalse(reviewed_receipt_matches(self.root))
        self.assertFalse(prior_fire_receipts_safe(self.root))

    def test_review_never_mutates_broker_or_halt(self):
        halt = self.root / "btc-auto-demo-halt"
        halt.touch()
        before = self.dbpath.read_bytes()
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.assertTrue(halt.exists())
        self.assertEqual(before, self.dbpath.read_bytes())


if __name__ == "__main__":
    unittest.main()
