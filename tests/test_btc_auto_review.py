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

    def test_historical_generic_risk_failure_requires_reproduced_low_net_rr(self):
        """An old generic risk failure is reviewable only if independently explained."""
        with sqlite3.connect(self.dbpath) as db:
            db.execute("CREATE TABLE fire_model_inputs(press TEXT PRIMARY KEY, snapshot TEXT)")
            snap = {
                "environment": "delta-india-demo",
                "fire_execution_scope": {"unattended_demo_mode": True},
                "core": {"best_bid": "60897.5", "best_ask": "60898.5"},
            }
            db.execute("INSERT INTO fire_model_inputs VALUES (?,?)",
                       (PRESS, json.dumps(snap)))
            outcome = {
                "reason_code": "risk_governor_failed",
                "orders_submitted": False,
                "protection_verified": False,
                "direction": "LONG", "contracts": 1, "selected_leverage": 5,
                "stop_loss": "60770", "take_profit": "61140",
                "decision_quote": {"best_bid": "60897.5", "best_ask": "60898.5"},
                "budget": {
                    "leverage": "5", "equity_usd": "149.65",
                    "contract_value": "0.001",
                    "max_contracts_per_entry": 2,
                    "taker_commission_rate": "0.0005",
                },
            }
            db.execute("UPDATE fire_requests SET result=? WHERE press=?",
                       (json.dumps(outcome), PRESS))
        found = evidence(self.root)
        self.assertEqual(found["reason_code"], "risk_governor_failed")
        with self.assertRaises(ValueError):
            acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        from tradebot.btc_auto_review import RISK_APPROVAL
        approved = acknowledge(
            self.root, approval=RISK_APPROVAL, candidate=lambda root: True)
        self.assertEqual(approved["status"], "reviewed_no_order")
        self.assertTrue(reviewed_receipt_matches(self.root))
        self.assertTrue(prior_fire_receipts_safe(self.root))
        # The legacy receipt can proceed only after matching signed review;
        # the separate halt latch still requires its own incident-specific
        # release path. New warning-only receipts take the normal path.
        with sqlite3.connect(self.dbpath) as db:
            db.execute("UPDATE fire_requests SET result=? WHERE press=?",
                       (json.dumps({**outcome, "take_profit": "62000"}), PRESS))
        self.assertIsNone(evidence(self.root))
        self.assertFalse(reviewed_receipt_matches(self.root))

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

    def test_subsequent_review_keeps_earlier_marker_and_halt(self):
        """An older reviewed failure must not prevent the next real review."""
        original = acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.assertEqual(original["status"], "reviewed_no_order")
        old_marker = self.root / MARKER_NAME
        original_bytes = old_marker.read_bytes()
        halt = self.root / "btc-auto-demo-halt"
        halt.touch()
        next_press = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        self.insert(next_press)
        self.assertFalse(reviewed_receipt_matches(self.root))
        self.assertFalse(prior_fire_receipts_safe(self.root))
        with self.assertRaises(ValueError):
            acknowledge(self.root, approval=APPROVAL, candidate=lambda root: False)
        scoped = self.root / f"btc-auto-reviewed-no-order-{next_press}.json"
        self.assertFalse(scoped.exists())
        report = acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.assertEqual(report["status"], "reviewed_no_order")
        self.assertEqual(old_marker.read_bytes(), original_bytes)
        self.assertTrue(scoped.exists())
        self.assertEqual(scoped.stat().st_mode & 0o777, 0o600)
        self.assertTrue(reviewed_receipt_matches(self.root))
        self.assertTrue(prior_fire_receipts_safe(self.root))
        self.assertEqual(
            acknowledge(self.root, approval=APPROVAL, candidate=lambda root: self.fail("broker called"))["status"],
            "already_reviewed")
        self.assertTrue(halt.exists())

        # A third failure must require its own independent signed approval.
        another_press = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        self.insert(another_press)
        self.assertFalse(reviewed_receipt_matches(self.root))
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.assertTrue(reviewed_receipt_matches(self.root))
        self.assertEqual(old_marker.read_bytes(), original_bytes)
        self.assertTrue(scoped.exists())
        self.assertTrue(halt.exists())

    def test_receipt_scoped_marker_rejects_mismatch_and_bad_permissions(self):
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        self.insert("cccccccccccccccccccccccccccccccc")
        acknowledge(self.root, approval=APPROVAL, candidate=lambda root: True)
        marker = self.root / "btc-auto-reviewed-no-order-cccccccccccccccccccccccccccccccc.json"
        self.assertTrue(reviewed_receipt_matches(self.root))
        marker.chmod(0o644)
        self.assertFalse(reviewed_receipt_matches(self.root))
        marker.chmod(0o600)
        self.assertTrue(reviewed_receipt_matches(self.root))
        marker.write_text(json.dumps({"press": "cccccccccccccccccccccccccccccccc", "reason_code": "fake"}))
        self.assertFalse(reviewed_receipt_matches(self.root))

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
