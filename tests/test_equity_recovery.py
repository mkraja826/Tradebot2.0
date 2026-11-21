from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest

from equity_fixtures import receipt_for
from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.portfolio_equity_guard import PortfolioEquityGuard

UTC = timezone.utc


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "risk.sqlite"
        self.guard = PortfolioEquityGuard(self.path)

    def test_month_year_and_monday_rollovers(self):
        for now in (datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC),
                    datetime(2027, 2, 1, tzinfo=UTC)):
            at = now + timedelta(minutes=1)
            self.guard.observe_verified_read("1000", receipt_for(at=at), now=at)
            health = checkpoint_health(self.path, at=at)
            self.assertEqual(health["daily_checkpoint"], "verified")
            self.assertEqual(health["weekly_checkpoint"],
                             "verified" if now.weekday() == 0 else "missed_window")
            self.assertEqual(datetime.fromisoformat(health["daily_next_window_start_utc"]),
                             now + timedelta(days=1))

    def test_exact_window_edges_and_missed_windows_after_reboot(self):
        monday = datetime(2026, 11, 23, tzinfo=UTC)
        health = checkpoint_health(self.path, at=monday + timedelta(minutes=5))
        self.assertEqual(health["daily_checkpoint"], "pending_window")
        edge = monday + timedelta(minutes=5)
        self.guard.observe_verified_read("1000", receipt_for(at=edge), now=edge)
        self.assertEqual(checkpoint_health(self.path, at=edge)[
            "weekly_checkpoint"], "verified")
        # A new process after next week's missed window cannot turn a later
        # current wallet balance into the opening it did not observe.
        late = monday + timedelta(days=7, minutes=5, microseconds=1)
        result = PortfolioEquityGuard(self.path).observe_verified_read(
            "1000", receipt_for(at=late), now=late)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "missing_opening_equity_checkpoint")

    def test_clock_reversal_is_reported_distinctly(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe("1000", at=at)
        report = checkpoint_health(self.path, at=at - timedelta(seconds=1))
        self.assertIn("equity_clock_inconsistent", report["alert_codes"])
        self.assertFalse(report["checkpoint_prerequisites_met"])

    def test_database_corruption_fails_closed_without_repair(self):
        bad = self.path.with_name("corrupt.sqlite")
        original = b"not a sqlite database: forensic original"
        bad.write_bytes(original)
        report = checkpoint_health(bad)
        self.assertFalse(report["checkpoint_prerequisites_met"])
        self.assertEqual(report["database_integrity"], "failed")
        self.assertIn("equity_ledger_integrity_failed", report["alert_codes"])
        self.assertEqual(bad.read_bytes(), original)

    def test_symlink_is_never_followed(self):
        link = self.path.with_name("link.sqlite")
        link.symlink_to(self.path)
        self.assertEqual(checkpoint_health(link)["status"], "evidence_unavailable")

    def test_staleness_uses_exact_boundary_without_rounding_down(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe_verified_read("1000", receipt_for(at=at), now=at)
        self.assertEqual(checkpoint_health(self.path, at=at + timedelta(seconds=180))[
            "observation_status"], "fresh")
        self.assertEqual(checkpoint_health(self.path, at=at + timedelta(seconds=180, microseconds=1))[
            "observation_status"], "stale")

    def test_legacy_migration_preserves_history_and_cannot_attest_old_receipts(self):
        path = self.path.with_name("legacy.sqlite")
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        observed_us = int(at.timestamp() * 1_000_000)
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE equity_evidence(observed_us INTEGER PRIMARY KEY,
                    equity_usd TEXT NOT NULL,origin TEXT NOT NULL CHECK(origin='delta_demo_signed_wallet'));
                CREATE TABLE equity_watermark(singleton INTEGER PRIMARY KEY CHECK(singleton=1),high_usd TEXT NOT NULL);
            """)
            db.execute("INSERT INTO equity_evidence VALUES (?,?,'delta_demo_signed_wallet')", (observed_us,"1000"))
            db.execute("INSERT INTO equity_watermark VALUES (1,'1000')")
        PortfolioEquityGuard(path)
        PortfolioEquityGuard(path)  # migration idempotent
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT * FROM equity_evidence").fetchall(),
                             [(observed_us,"1000","delta_demo_signed_wallet")])
            self.assertEqual(db.execute("SELECT * FROM equity_read_receipts").fetchall(), [])
        legacy_health = checkpoint_health(path, at=at)
        self.assertFalse(legacy_health["checkpoint_prerequisites_met"])
        self.assertEqual(legacy_health["daily_checkpoint"], "unverified_receipt")
        self.assertEqual(legacy_health["weekly_checkpoint"], "unverified_receipt")
        self.assertEqual(legacy_health["latest_receipt_status"], "missing")
        self.assertIn("equity_read_receipt_invalid", legacy_health["alert_codes"])

    def test_historical_opening_without_transport_receipt_is_not_verified(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        latest = at + timedelta(minutes=2)
        self.guard.observe("1000", at=at)
        self.guard.observe_verified_read("1000", receipt_for(at=latest), now=latest)
        report = checkpoint_health(self.path, at=latest)
        self.assertEqual(report["daily_checkpoint"], "unverified_receipt")
        self.assertEqual(report["weekly_checkpoint"], "unverified_receipt")
        self.assertEqual(report["latest_receipt_status"], "verified")
        self.assertFalse(report["checkpoint_prerequisites_met"])
        self.assertIn("equity_read_receipt_invalid", report["alert_codes"])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_read_receipts").fetchone()[0], 1)

    def test_recent_unsigned_latest_observation_is_not_fresh_verified(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe_verified_read("1000", receipt_for(at=at), now=at)
        self.guard.observe("1000", at=at + timedelta(seconds=1))
        report = checkpoint_health(self.path, at=at + timedelta(seconds=1))
        self.assertEqual(report["daily_checkpoint"], "verified")
        self.assertEqual(report["weekly_checkpoint"], "verified")
        self.assertEqual(report["latest_receipt_status"], "missing")
        self.assertEqual(report["observation_status"], "unverified_receipt")
        self.assertIn("latest_equity_read_receipt_unverified", report["blocking_conditions"])
        self.assertFalse(report["checkpoint_prerequisites_met"])

    def test_mismatched_historical_equity_receipt_fails_closed(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe("1000", at=at)
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO equity_read_receipts VALUES (?,?)",
                       (int(at.timestamp()*1_000_000), json.dumps(receipt_for("5000", at))))
            db.commit()
        report = checkpoint_health(self.path, at=at)
        self.assertEqual(report["daily_checkpoint"], "unverified_receipt")
        self.assertEqual(report["latest_receipt_status"], "invalid")
        self.assertFalse(report["checkpoint_prerequisites_met"])

    def test_untrusted_receipt_timestamp_does_not_establish_opening(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe("1000", at=at)
        forged = receipt_for("1000", at)
        forged["received_us"] += 1_000_000
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO equity_read_receipts VALUES (?,?)",
                       (int(at.timestamp()*1_000_000), json.dumps(forged)))
            db.commit()
        result = checkpoint_health(self.path, at=at)
        self.assertEqual(result["weekly_checkpoint"], "unverified_receipt")
        self.assertFalse(result["checkpoint_prerequisites_met"])

    def test_concurrent_duplicate_read_commits_only_one_immutable_observation(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        receipt = receipt_for(at=at)
        def submit(_):
            return PortfolioEquityGuard(self.path).require_verified_read("1000", receipt, now=at)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(16)))
        self.assertTrue(all(r["approved"] for r in results))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 1)

    def test_sample_deduplication_and_health_cost_remain_bounded(self):
        # A production-shaped month of immutable minute observations. No network.
        at = datetime(2026, 11, 1, tzinfo=UTC)
        start_us = int(at.timestamp() * 1_000_000)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany("INSERT INTO equity_evidence VALUES (?,?,'delta_demo_signed_wallet')",
                           ((start_us + i * 60_000_000, "1000") for i in range(31 * 1440)))
            db.execute("INSERT INTO equity_watermark VALUES (1,'1000')")
        end = at + timedelta(days=30, hours=23, minutes=59)
        started = time.monotonic()
        for _ in range(10):
            health = checkpoint_health(self.path, at=end)
            self.assertFalse(health["checkpoint_prerequisites_met"])
            self.assertEqual(health["daily_checkpoint"], "unverified_receipt")
            self.assertEqual(health["latest_receipt_status"], "missing")
        self.assertLess(time.monotonic() - started, 3)

    def test_loss_limits_still_reject_exact_boundaries_after_receipt_validation(self):
        monday = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe_verified_read("1000", receipt_for(at=monday), now=monday)
        for minutes, value in ((1, "980"), (2, "950"), (3, "920")):
            at = monday + timedelta(minutes=minutes)
            report = self.guard.observe_verified_read(value, receipt_for(value,at), now=at)
            self.assertFalse(report["approved"])
            self.assertIn("daily", report["reason"])
            if value == "950":
                self.assertIn("weekly", report["reason"])
            if value == "920":
                self.assertIn("drawdown", report["reason"])

    def test_online_backup_restore_preserves_openings_receipts_and_peak(self):
        at = datetime(2026, 11, 23, 0, 1, tzinfo=UTC)
        self.guard.observe_verified_read("1000", receipt_for(at=at), now=at)
        backup = self.path.with_name("restored.sqlite")
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
            self.assertEqual(target.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            for table in ("equity_evidence", "equity_read_receipts", "equity_watermark"):
                self.assertEqual(source.execute(f"SELECT * FROM {table}").fetchall(),
                                 target.execute(f"SELECT * FROM {table}").fetchall())
        self.assertTrue(checkpoint_health(backup, at=at)["checkpoint_prerequisites_met"])
