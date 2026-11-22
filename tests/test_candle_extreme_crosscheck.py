"""Offline BTC abnormal-candle cross-venue selection and safety tests."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tradebot.candle_extreme_crosscheck import (
    MAX_CANDIDATES, inspect_archive_extremes, crosscheck_archive_extremes,
    main,
)
from tradebot.delta import DEMO_API

OCT = int(datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc).timestamp())
NOV = int(datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc).timestamp())
NOW = datetime(2026, 11, 22, 10, 30, tzinfo=timezone.utc)


class FakeExchange:
    base_url = DEMO_API
    allow_orders = False


class ExtremeCrosscheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="candle-venue-offline-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "delta-demo-candles.sqlite"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE candles (
                    symbol TEXT, t INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
                    PRIMARY KEY(symbol,t));
                CREATE TABLE candle_quarantine(
                    symbol TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,v REAL,
                    reason TEXT, PRIMARY KEY(symbol,t));
                CREATE TABLE coverage(
                    symbol TEXT PRIMARY KEY, floor INTEGER,
                    oldest_scan INTEGER, newest_scan INTEGER);
            """)

    def populate(self, *, anomaly=True):
        with sqlite3.connect(self.path) as db:
            for origin in (OCT, NOV):
                for n in range(7):
                    high = 250000.0 if anomaly and n == 3 else 60100.0
                    db.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?)", (
                        "BTCUSD", origin + n*300, 60000., high, 59900., 60000., 1.))
            db.commit()

    def test_release_audit_includes_crossvenue_context(self):
        # Dedicated assertion avoids a merge conflict with equity release
        # guards adding different checks to the shared operator audit test.
        root = Path(__file__).resolve().parents[1]
        audit = (root / "ops" / "run_btc_demo_release_audit.sh").read_text()
        self.assertIn("tradebot.candle_extreme_crosscheck", audit)
        self.assertIn("TRADING_ENABLED: false", audit)

    def test_selects_exact_extreme_utc_buckets_from_both_months(self):
        self.populate()
        first = self.path.read_bytes()
        report = inspect_archive_extremes(self.root, now=NOW)
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["selected_count"], 2)
        self.assertFalse(report["candidate_examples_truncated"])
        self.assertEqual(report["timestamps_utc"], [
            datetime.fromtimestamp(OCT + 900, timezone.utc).isoformat(),
            datetime.fromtimestamp(NOV + 900, timezone.utc).isoformat(),
        ])
        self.assertEqual(self.path.read_bytes(), first)
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_public_check_has_fixed_sources_and_no_economic_or_order_calls(self):
        self.populate()
        seen = []
        def context(exchange, times, **kwargs):
            self.assertIsInstance(exchange, FakeExchange)
            seen.extend(times)
            return {
                "status": "cross_venue_spot_context_complete_manual_review_required",
                "blockers": [],
                "results": [{"utc": datetime.fromtimestamp(t,timezone.utc).isoformat(),
                             "comparison": "source_crosscheck_complete_not_independent_proof"}
                            for t in times],
            }
        before = self.path.read_bytes()
        report = crosscheck_archive_extremes(
            self.root, now=NOW, exchange=FakeExchange(), context_check=context)
        self.assertEqual(seen, [OCT+900, NOV+900])
        self.assertEqual(report["reason"],
                         "cross_venue_context_available_for_independent_review")
        self.assertEqual(report["cross_venue_report"]["trade_authorized"], False)
        self.assertFalse(report["independent_perpetual_price_proven"])
        self.assertFalse(report["quarantine_release_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertNotIn("_candidate_times", report)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_broker_client_rejected_before_external_network(self):
        self.populate()
        client = FakeExchange()
        client.allow_orders = True
        def never(*args, **kwargs):
            raise AssertionError("No external source may be called")
        report = crosscheck_archive_extremes(
            self.root, now=NOW, exchange=client, context_check=never)
        self.assertEqual(report["reason"], "read_only_demo_client_required")
        self.assertFalse(report["safe_to_enable_fire"])

    def test_missing_archive_does_not_create_database_or_call_network(self):
        self.path.unlink()
        def never(*args, **kwargs):
            raise AssertionError("No external source may be called")
        report = crosscheck_archive_extremes(
            self.root, now=NOW, context_check=never)
        self.assertEqual(report["reason"], "trusted_original_archive_required")
        self.assertFalse(self.path.exists())
        self.assertFalse(report["trade_authorized"])

    def test_ordinary_prices_do_not_trigger_external_requests(self):
        self.populate(anomaly=False)
        def never(*args, **kwargs):
            raise AssertionError("No network for ordinary local price extrema")
        result = crosscheck_archive_extremes(
            self.root, now=NOW, exchange=FakeExchange(), context_check=never)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["reason"],
                         "no_candidate_extreme_not_market_validation")
        self.assertFalse(result["independent_perpetual_price_proven"])

    def test_attempt_limit_rejects_booleans_zero_and_large(self):
        self.populate()
        for cap in (0, -1, True, 5, 100):
            with self.subTest(cap=cap):
                result = inspect_archive_extremes(
                    self.root, now=NOW, max_candidates=cap)
                self.assertEqual(result["reason"], "invalid_candidate_limit")
                self.assertFalse(result["trade_authorized"])

    def test_remote_failure_is_sanitized_not_false_release(self):
        self.populate()
        def fail(*args, **kwargs):
            raise RuntimeError("SECRET_PRIVATE_ACCOUNT_ACCESS_KEY")
        report = crosscheck_archive_extremes(
            self.root, now=NOW, exchange=FakeExchange(), context_check=fail)
        self.assertEqual(report["reason"], "cross_venue_observation_unavailable")
        self.assertNotIn("SECRET_", json.dumps(report))
        self.assertFalse(report["safe_to_enable_fire"])

    def test_cli_always_returns_nonzero_even_if_crosscheck_completes(self):
        with patch("tradebot.candle_extreme_crosscheck.crosscheck_archive_extremes",
                   return_value={"status": "cross_venue_spot_context_complete",
                                 "trade_authorized": False}) as check:
            with patch("builtins.print"):
                code = main(["--data-dir", str(self.root), "--max-candidates", "2"])
        self.assertEqual(code, 2)
        check.assert_called_once_with(str(self.root), max_candidates=2)

    def test_candidate_request_budget_is_bounded(self):
        self.populate()
        report = inspect_archive_extremes(
            self.root, now=NOW, max_candidates=1)
        self.assertEqual(report["selected_count"], 1)
        self.assertTrue(report["candidate_examples_truncated"])
        self.assertLessEqual(report["selected_count"], MAX_CANDIDATES)


if __name__ == "__main__":
    unittest.main()
