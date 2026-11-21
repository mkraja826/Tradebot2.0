"""Runtime must never bootstrap replacement loss history after evidence loss."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from equity_fixtures import receipt_for
from tradebot.portfolio_equity_guard import EquityRiskError, PortfolioEquityGuard, RuntimeEquityGuard


class MockDemoWallet:
    base_url = "https://cdn-ind.testnet.deltaex.org"
    def __init__(self, equity, at):
        self.equity, self.at = equity, at
    def wallet_balances(self):
        return {"meta": {"net_equity": self.equity},
                "equity_read_receipt": receipt_for(self.equity, self.at)}


class RuntimeIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "risk.sqlite"
        self.now = datetime(2026, 11, 23, 0, 1, tzinfo=timezone.utc)

    def seed(self):
        guard = PortfolioEquityGuard(self.path)
        guard.observe_verified_read("2000", receipt_for("2000", self.now),
                                     now=self.now)
        return guard

    def check(self, guard, equity="2000", seconds=1):
        at = self.now + timedelta(seconds=seconds)
        return guard.require_verified_read(equity, receipt_for(equity, at), now=at)

    def test_lazy_runtime_does_not_create_paths_or_a_new_baseline(self):
        path = self.root / "absent" / "risk.sqlite"
        runtime = RuntimeEquityGuard(path)
        self.assertFalse(path.parent.exists())
        with self.assertRaises(EquityRiskError):
            self.check(runtime)
        self.assertFalse(path.parent.exists())

    def test_empty_file_is_missing_history_not_provisioning_permission(self):
        self.path.touch()
        with self.assertRaises((EquityRiskError, sqlite3.Error)):
            self.check(RuntimeEquityGuard(self.path))
        self.assertEqual(self.path.read_bytes(), b"")

    def test_empty_existing_schema_cannot_adopt_current_equity_as_its_opening(self):
        PortfolioEquityGuard(self.path)
        with self.assertRaisesRegex(EquityRiskError, "history_or_watermark_missing"):
            self.check(RuntimeEquityGuard(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM equity_watermark").fetchone()[0], 0)

    def test_existing_legacy_ledger_migrates_without_resetting_original_peak(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE equity_evidence(observed_us INTEGER PRIMARY KEY,equity_usd TEXT NOT NULL,
                    origin TEXT NOT NULL CHECK(origin='delta_demo_signed_wallet'));
                CREATE TABLE equity_watermark(singleton INTEGER PRIMARY KEY CHECK(singleton=1),high_usd TEXT NOT NULL);
            """)
            db.execute("INSERT INTO equity_evidence VALUES (?,?,'delta_demo_signed_wallet')",
                       (int(self.now.timestamp()*1000000), "2000"))
            db.execute("INSERT INTO equity_watermark VALUES (1,'2000')")
        with self.assertRaisesRegex(EquityRiskError, "equity_checkpoint_receipt_missing"):
            self.check(RuntimeEquityGuard(self.path), "1000")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT high_usd FROM equity_watermark").fetchone(), ("2000",))
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM equity_read_receipts").fetchone()[0], 0)

    def test_missing_watermark_rejected_before_additive_migration(self):
        self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM equity_watermark")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(EquityRiskError, "history_or_watermark_missing"):
            self.check(RuntimeEquityGuard(self.path))
        self.assertEqual(self.path.read_bytes(), before)

    def test_file_removed_after_startup_is_not_recreated_by_sqlite(self):
        self.seed()
        guard = RuntimeEquityGuard(self.path)
        self.check(guard)
        preserved = self.path.with_name("preserved.sqlite")
        self.path.rename(preserved)
        with self.assertRaises(EquityRiskError):
            self.check(guard, seconds=2)
        self.assertFalse(self.path.exists())

    def test_valid_different_ledger_cannot_replace_open_runtime_history(self):
        self.seed()
        guard = RuntimeEquityGuard(self.path)
        self.check(guard)
        self.path.rename(self.path.with_name("original.sqlite"))
        substitute = PortfolioEquityGuard(self.path)
        substitute.observe("1000", at=self.now)
        with self.assertRaisesRegex(EquityRiskError, "ledger_replaced"):
            self.check(guard, "1000", seconds=2)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 1)

    def test_symlink_replacement_cannot_read_or_write_another_ledger(self):
        self.seed()
        guard = RuntimeEquityGuard(self.path)
        self.check(guard)
        preserved = self.path.with_name("original.sqlite")
        self.path.rename(preserved)
        self.path.symlink_to(preserved)
        before = preserved.read_bytes()
        with self.assertRaisesRegex(EquityRiskError, "ledger_replaced"):
            self.check(guard, seconds=2)
        self.assertEqual(preserved.read_bytes(), before)

    def test_deletion_between_identity_check_and_connect_uses_noncreating_mode(self):
        self.seed()
        guard = PortfolioEquityGuard(self.path, require_existing=True)
        connect = sqlite3.connect
        def race(target, **kwargs):
            self.path.rename(self.path.with_name("preserved.sqlite"))
            return connect(target, **kwargs)
        with patch("tradebot.portfolio_equity_guard.sqlite3.connect", side_effect=race):
            with self.assertRaises(sqlite3.OperationalError):
                self.check(guard)
        self.assertFalse(self.path.exists())

    def test_existing_only_rejects_unsigned_opening_before_observation_write(self):
        guard = PortfolioEquityGuard(self.path)
        guard.observe("2000", at=self.now)
        instant = self.now + timedelta(seconds=1)
        before = guard.latest_observed_us()
        with self.assertRaisesRegex(EquityRiskError, "equity_checkpoint_receipt_missing"):
            RuntimeEquityGuard(self.path).require_verified_read(
                "2000", receipt_for("2000", instant), now=instant)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM equity_read_receipts").fetchone()[0], 0)
        self.assertEqual(guard.latest_observed_us(), before)

    def test_existing_only_rejects_unsigned_latest_after_verified_opening(self):
        guard = self.seed()
        latest = self.now + timedelta(seconds=1)
        guard.observe("2000", at=latest)
        requested = self.now + timedelta(seconds=2)
        with self.assertRaisesRegex(EquityRiskError, "equity_checkpoint_receipt_missing"):
            RuntimeEquityGuard(self.path).require_verified_read(
                "2000", receipt_for("2000", requested), now=requested)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM equity_read_receipts").fetchone()[0], 1)

    def test_collector_can_record_diagnostic_sample_but_cannot_approve_old_anchor(self):
        guard = PortfolioEquityGuard(self.path)
        guard.observe("2000", at=self.now)
        instant = self.now + timedelta(seconds=1)
        report = RuntimeEquityGuard(self.path).observe_signed_demo(
            MockDemoWallet("2000", instant))
        self.assertTrue(report["approved"])  # diagnostic arithmetic only
        requested = self.now + timedelta(seconds=2)
        with self.assertRaisesRegex(EquityRiskError, "equity_checkpoint_receipt_missing"):
            RuntimeEquityGuard(self.path).require_verified_read(
                "2000", receipt_for("2000", requested), now=requested)

    def test_exact_original_receipt_mismatch_cannot_approve_runtime_equity(self):
        guard = PortfolioEquityGuard(self.path)
        guard.observe("2000", at=self.now)
        with closing(sqlite3.connect(self.path)) as db, db:
            altered = receipt_for("999", self.now)
            db.execute("INSERT INTO equity_read_receipts VALUES (?,?)",
                       (int(self.now.timestamp()*1_000_000), json.dumps(altered)))
        instant = self.now + timedelta(seconds=1)
        with self.assertRaisesRegex(EquityRiskError, "equity_checkpoint_receipt_unverified"):
            RuntimeEquityGuard(self.path).require_verified_read(
                "2000", receipt_for("2000", instant), now=instant)

    def test_concurrent_existing_only_opens_preserve_one_receipt_and_peak(self):
        self.seed()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _:self.check(RuntimeEquityGuard(self.path)), range(12)))
        self.assertTrue(all(r["approved"] for r in results))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM equity_read_receipts").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT high_usd FROM equity_watermark").fetchone(), ("2000",))


if __name__ == "__main__":
    unittest.main()
