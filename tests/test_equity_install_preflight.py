"""No-network/no-order tests for stage-only equity collector schema admission."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from tradebot.equity_install_preflight import inspect_collector_schema, main
from tradebot.portfolio_equity_guard import PortfolioEquityGuard


class EquityInstallPreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db_path = self.root / "fire-equity-risk.sqlite"

    def inspect(self):
        return inspect_collector_schema(self.root)

    def test_missing_ledger_never_creates_file(self):
        result = self.inspect()
        self.assertEqual(result["reason"], "existing_ledger_unavailable")
        self.assertFalse(result["unit_schema_prerequisites_met"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(self.db_path.exists())

    def test_legacy_verified_sqlite_requires_receipt_migration_and_no_writes(self):
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE equity_evidence(observed_us INTEGER PRIMARY KEY,
                    equity_usd TEXT NOT NULL, origin TEXT NOT NULL);
                CREATE TABLE equity_watermark(singleton INTEGER PRIMARY KEY,
                    high_usd TEXT NOT NULL);
                INSERT INTO equity_evidence VALUES
                    (1795392060000000,'1000','delta_demo_signed_wallet');
                INSERT INTO equity_watermark VALUES(1,'1000');
            """)
        before = self.db_path.read_bytes()
        result = self.inspect()
        self.assertTrue(result["ledger_integrity_verified"])
        self.assertEqual(result["reason"], "receipt_schema_migration_required")
        self.assertFalse(result["unit_schema_prerequisites_met"])
        self.assertFalse(result["opening_checkpoint_verified"])
        self.assertEqual(self.db_path.read_bytes(), before)
        with sqlite3.connect(self.db_path) as db:
            self.assertFalse(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='equity_read_receipts'"
            ).fetchone())

    def test_valid_migrated_schema_not_trading_clearance(self):
        guard = PortfolioEquityGuard(self.db_path)
        guard.observe("1000", at=datetime(2026, 11, 20, tzinfo=timezone.utc))
        before = self.db_path.read_bytes()
        result = self.inspect()
        self.assertEqual(result["status"],
                         "schema_prerequisites_met_not_release_authority")
        self.assertEqual(result["reason"], "none")
        self.assertTrue(result["unit_schema_prerequisites_met"])
        for field in ("opening_checkpoint_verified", "trade_authorized",
                      "safe_to_enable_fire", "local_ledger_mutations",
                      "broker_order_mutations"):
            self.assertIs(result[field], False, field)
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_missing_immutable_trigger_blocks_even_if_schema_exists(self):
        guard = PortfolioEquityGuard(self.db_path)
        guard.observe("1000", at=datetime(2026, 11, 20, tzinfo=timezone.utc))
        with sqlite3.connect(self.db_path) as db:
            db.execute("DROP TRIGGER reject_equity_receipt_update")
        result = self.inspect()
        self.assertEqual(result["reason"], "immutable_evidence_triggers_missing")
        self.assertFalse(result["unit_schema_prerequisites_met"])

    def test_lowered_peak_blocks_installation(self):
        guard = PortfolioEquityGuard(self.db_path)
        guard.observe("1000", at=datetime(2026, 11, 20, tzinfo=timezone.utc))
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE equity_watermark SET high_usd='1'")
        result = self.inspect()
        self.assertEqual(result["reason"], "historical_watermark_unverified")
        self.assertFalse(result["unit_schema_prerequisites_met"])

    def test_corrupt_sqlite_fails_closed(self):
        self.db_path.write_bytes(b"not a sqlite database")
        result = self.inspect()
        self.assertEqual(result["reason"], "ledger_integrity_unverified")
        self.assertFalse(result["unit_schema_prerequisites_met"])

    def test_symlinked_ledger_refused(self):
        other = self.root / "original.sqlite"
        other.write_bytes(b"not a valid database")
        self.db_path.symlink_to(other)
        result = self.inspect()
        self.assertEqual(result["reason"], "existing_ledger_unavailable")

    def test_cli_missing_ledger_reports_nonzero(self):
        with patch("builtins.print"):
            self.assertEqual(main(["--data-dir", str(self.root)]), 2)
        self.assertFalse(self.db_path.exists())


if __name__ == "__main__":
    unittest.main()
