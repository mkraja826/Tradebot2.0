"""Older immutable peaks must survive rollover, corruption and process reuse."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from equity_fixtures import receipt_for
from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.portfolio_equity_guard import EquityRiskError, PortfolioEquityGuard, RuntimeEquityGuard


class HistoricalWatermarkTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "risk.sqlite"
        self.now = datetime(2026, 11, 23, 0, 1, tzinfo=timezone.utc)

    def seed(self, peak="1100", latest="1000"):
        guard = PortfolioEquityGuard(self.path)
        previous = self.now - timedelta(days=1)
        guard.observe_verified_read(peak, receipt_for(peak, previous), now=previous)
        return guard.observe_verified_read(latest, receipt_for(latest, self.now),
                                           now=self.now)

    def overwrite_peak(self, value):
        # Fault injection into an isolated fixture, never a recovery operation.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE equity_watermark SET high_usd=? WHERE singleton=1", (value,))

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return "\n".join(db.iterdump())

    def read(self, runtime, equity="1000", seconds=1):
        at = self.now + timedelta(seconds=seconds)
        return runtime.require_verified_read(equity, receipt_for(equity, at), now=at)

    def test_restart_rejects_lowered_historical_peak_without_repair(self):
        self.assertEqual(self.seed()["reason"], "loss_limit_drawdown")
        self.overwrite_peak("1000")
        before = self.snapshot()
        for _ in range(2):
            with self.assertRaisesRegex(EquityRiskError, "watermark_inconsistent"):
                self.read(RuntimeEquityGuard(self.path))
        self.assertEqual(self.snapshot(), before)

    def test_cached_runtime_revalidates_older_peak_before_every_observation(self):
        self.seed()
        runtime = RuntimeEquityGuard(self.path)
        with self.assertRaisesRegex(EquityRiskError, "loss_limit_drawdown"):
            self.read(runtime)
        self.overwrite_peak("1000")
        before = self.snapshot()
        with self.assertRaisesRegex(EquityRiskError, "watermark_inconsistent"):
            self.read(runtime, seconds=2)
        self.assertEqual(self.snapshot(), before)

    def test_health_rejects_lowered_peak_despite_fresh_genuine_openings(self):
        self.seed()
        self.overwrite_peak("1000")
        before = self.snapshot()
        health = checkpoint_health(self.path, at=self.now)
        self.assertFalse(health["checkpoint_prerequisites_met"])
        self.assertFalse(health["trade_authorized"])
        self.assertEqual(health["database_integrity"], "failed")
        self.assertIn("equity_ledger_integrity_failed", health["alert_codes"])
        self.assertEqual(self.snapshot(), before)

    def test_later_higher_wallet_cannot_silently_repair_inconsistent_history(self):
        self.seed()
        self.overwrite_peak("1000")
        before = self.snapshot()
        with self.assertRaisesRegex(EquityRiskError, "watermark_inconsistent"):
            self.read(RuntimeEquityGuard(self.path), "1200")
        self.assertEqual(self.snapshot(), before)

    def test_decimal_comparison_handles_text_order_exponents_and_sub_float_gaps(self):
        for peak, latest in (("1000", "999"), ("1E+3", "900"),
                             ("1000.00000000000000000001", "1000")):
            with self.subTest(peak=peak, latest=latest), TemporaryDirectory() as root:
                original = self.path
                self.path = Path(root) / "risk.sqlite"
                self.seed(peak, latest)
                self.overwrite_peak(latest)
                before = self.snapshot()
                with self.assertRaisesRegex(EquityRiskError, "watermark_inconsistent"):
                    self.read(RuntimeEquityGuard(self.path), latest)
                self.assertEqual(self.snapshot(), before)
                self.path = original

    def test_higher_stored_watermark_is_preserved_as_conservative_risk_evidence(self):
        self.seed()
        self.overwrite_peak("1200")
        with self.assertRaisesRegex(EquityRiskError, "loss_limit_drawdown"):
            self.read(RuntimeEquityGuard(self.path))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT high_usd FROM equity_watermark").fetchone(), ("1200",))

    def test_invalid_legacy_peak_is_rejected_before_additive_migration(self):
        self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE equity_read_receipts")
        self.overwrite_peak("1000")
        before = self.snapshot()
        with self.assertRaisesRegex(EquityRiskError, "watermark_inconsistent"):
            self.read(RuntimeEquityGuard(self.path))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
