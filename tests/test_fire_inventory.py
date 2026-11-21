"""No-network, no-order tests for local FIRE receipt inventory coverage."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tradebot.fire_inventory import InventoryEvidenceError, read_inventory, main


BTC = "a" * 32
GOLD = "b" * 32
UTC = "2026-11-20T10:00:00+00:00"


class FireInventoryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("fire-ops.sqlite", "fire-xaut.sqlite"):
            with sqlite3.connect(self.root / name) as db:
                db.execute("CREATE TABLE fire_requests("
                           "press TEXT PRIMARY KEY, created_at TEXT NOT NULL,"
                           "updated_at TEXT NOT NULL, status TEXT NOT NULL,"
                           "result TEXT NOT NULL)")
        with sqlite3.connect(self.root / "fire-reconciliation.sqlite") as db:
            db.execute("CREATE TABLE reports("
                       "digest TEXT PRIMARY KEY, trade_key TEXT NOT NULL, body TEXT NOT NULL)")

    def add_receipt(self, market, fireid, status, submitted, *, body=None):
        name = "fire-ops.sqlite" if market == "BTCUSD" else "fire-xaut.sqlite"
        result = {"orders_submitted": submitted} if body is None else body
        with sqlite3.connect(self.root / name) as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (fireid, UTC, UTC, status, json.dumps(result)))

    def add_report(self, key, body=None, *, marker="1"):
        with sqlite3.connect(self.root / "fire-reconciliation.sqlite") as db:
            db.execute("INSERT INTO reports VALUES (?,?,?)",
                       (marker, key, json.dumps(body or {"is_net_realized_pnl": False})))

    def test_empty_local_inventory_never_claims_account_profit_or_flatness(self):
        report = read_inventory(self.root)
        self.assertEqual(report["total_local_receipts"], 0)
        self.assertFalse(report["is_account_flatness_verified"])
        self.assertFalse(report["is_account_realized_pnl"])
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["financial_values_reported"])
        self.assertEqual(report["broker_calls"], 0)
        self.assertEqual(report["ai_calls"], 0)

    def test_no_order_label_is_explicitly_local_not_broker_proof(self):
        self.add_receipt("XAUTUSD", GOLD, "rejected_no_order", False)
        report = read_inventory(self.root)
        self.assertEqual(report["locally_reported_no_order_count"], 1)
        self.assertEqual(report["requires_broker_review_count"], 0)
        self.assertEqual(report["entries"][0]["category"], "locally_reported_no_order")
        self.assertFalse(report["is_account_flatness_verified"])

    def test_unknown_submission_or_inflight_requires_broker_review(self):
        self.add_receipt("BTCUSD", BTC, "flat_verified", None)
        self.add_receipt("XAUTUSD", GOLD, "exposure_unknown", True)
        report = read_inventory(self.root)
        self.assertEqual(report["requires_broker_review_count"], 2)
        self.assertEqual(report["evidence_status"], "incomplete_or_ambiguous")

    def test_closed_receipt_missing_financial_review_is_not_profit(self):
        self.add_receipt("BTCUSD", BTC, "flat_verified", True)
        report = read_inventory(self.root)
        self.assertEqual(report["locally_reported_flat_count"], 1)
        self.assertEqual(report["flat_receipts_missing_financial_review_count"], 1)
        self.assertFalse(report["is_account_realized_pnl"])
        self.assertEqual(report["evidence_status"], "incomplete_or_ambiguous")

    def test_matching_local_financial_report_only_proves_record_presence(self):
        self.add_receipt("BTCUSD", BTC, "flat_verified", True)
        self.add_report("BTCUSD:" + BTC, {"is_net_realized_pnl": True,
                                         "net_realized_pnl_usd": "1000000"})
        report = read_inventory(self.root)
        self.assertEqual(report["flat_receipts_missing_financial_review_count"], 0)
        self.assertTrue(report["entries"][0]["local_financial_report_present"])
        self.assertNotIn("net_realized_pnl_usd", json.dumps(report))
        self.assertFalse(report["is_account_realized_pnl"])

    def test_reconciliation_without_receipt_is_orphan_not_account_profit(self):
        self.add_report("BTCUSD:" + BTC)
        report = read_inventory(self.root)
        self.assertEqual(report["unmatched_financial_report_keys_count"], 1)
        self.assertEqual(report["evidence_status"], "incomplete_or_ambiguous")
        self.assertFalse(report["is_account_flatness_verified"])

    def test_missing_source_database_is_not_recreated(self):
        missing = self.root / "fire-xaut.sqlite"
        missing.unlink()
        report = read_inventory(self.root)
        self.assertIn("fire-xaut.sqlite", report["missing_databases"])
        self.assertEqual(report["by_market"]["XAUTUSD"]["receipt_database"], "missing")
        self.assertIsNone(report["by_market"]["XAUTUSD"]["total_receipts"])
        self.assertFalse(missing.exists())
        self.assertEqual(report["evidence_status"], "incomplete_or_ambiguous")

    def test_missing_reconciliation_database_stays_missing(self):
        missing = self.root / "fire-reconciliation.sqlite"
        missing.unlink()
        self.add_receipt("BTCUSD", BTC, "flat_verified", True)
        report = read_inventory(self.root)
        self.assertIn("fire-reconciliation.sqlite", report["missing_databases"])
        self.assertEqual(report["flat_receipts_missing_financial_review_count"], 1)
        self.assertFalse(missing.exists())

    def test_invalid_json_or_timestamp_blocks_entire_report(self):
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (BTC, "2026-11-20T10:00:00", UTC, "flat_verified", "{}"))
        with self.assertRaisesRegex(InventoryEvidenceError, "invalid_receipt_timestamp"):
            read_inventory(self.root)
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("UPDATE fire_requests SET created_at=?,result=?",
                       (UTC, "{bad json"))
        with self.assertRaisesRegex(InventoryEvidenceError, "invalid_receipt_payload"):
            read_inventory(self.root)

    def test_untrusted_symlinked_sqlite_is_rejected(self):
        target = self.root / "fire-ops.sqlite"
        target.rename(self.root / "original.sqlite")
        target.symlink_to(self.root / "original.sqlite")
        with self.assertRaisesRegex(InventoryEvidenceError, "untrusted_database_path"):
            read_inventory(self.root)

    def test_corrupt_db_and_missing_schema_fail_closed_without_repair(self):
        path = self.root / "fire-ops.sqlite"
        path.write_bytes(b"corrupt bytes")
        before = path.read_bytes()
        with self.assertRaises(InventoryEvidenceError):
            read_inventory(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_financial_ownership_fails_closed(self):
        self.add_report("OTHER:" + BTC)
        with self.assertRaisesRegex(InventoryEvidenceError, "invalid_reconciliation_ownership"):
            read_inventory(self.root)

    def test_example_limit_does_not_change_counts_or_authority(self):
        self.add_receipt("BTCUSD", BTC, "flat_verified", True)
        self.add_receipt("XAUTUSD", GOLD, "rejected_no_order", False)
        report = read_inventory(self.root, limit=0)
        self.assertEqual(report["total_local_receipts"], 2)
        self.assertEqual(report["entries"], [])
        self.assertTrue(report["entries_truncated"])
        self.assertFalse(report["trade_authorized"])
        with self.assertRaisesRegex(InventoryEvidenceError, "invalid_example_limit"):
            read_inventory(self.root, limit=True)

    def test_cli_exit_status_reflects_missing_coverage(self):
        self.add_receipt("BTCUSD", BTC, "flat_verified", True)
        self.assertEqual(main(["--data-dir", str(self.root), "--limit", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
