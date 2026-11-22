"""Synthetic archive forensics: no broker, no model, no archive writes."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tradebot.candle_anomaly_inventory import inspect_window, inventory_archive

START = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
STEP = 300


class ArchiveInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / "delta-demo-candles.sqlite"
        with sqlite3.connect(self.dbpath) as db:
            db.executescript("""
                CREATE TABLE candles(symbol TEXT, t INTEGER, o REAL,
                    h REAL,l REAL,c REAL,v REAL, PRIMARY KEY(symbol,t));
                CREATE TABLE candle_quarantine(
                    symbol TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,v REAL,
                    reason TEXT,PRIMARY KEY(symbol,t));
                CREATE TABLE coverage(
                    symbol TEXT PRIMARY KEY, floor INTEGER, oldest_scan INTEGER,
                    newest_scan INTEGER);
            """)

    def add_candles(self, symbol, n=8):
        with sqlite3.connect(self.dbpath) as db:
            db.executemany(
                "INSERT INTO candles VALUES (?,?,?,?,?,?,?)",
                [(symbol, START + i*STEP, 100.0, 102.0, 99.0, 100.0, 1.0)
                 for i in range(n)])

    def test_full_small_window_no_issue(self):
        self.add_candles("BTCUSD")
        with sqlite3.connect(self.dbpath) as db:
            result = inspect_window(db, "BTCUSD", START, START+8*STEP)
        self.assertEqual(result["expected_bars"], 8)
        self.assertEqual(result["retained_bars"], 8)
        self.assertEqual(result["missing_bar_count"], 0)
        self.assertEqual(result["suspect_bar_count"], 0)
        self.assertEqual(result["issues"], [])
        self.assertNotIn("verified", result["quality_status"].replace("not_independently_verified", ""))

    def test_detects_missing_three_gold_bars_without_inventing_data(self):
        self.add_candles("XAUTUSD")
        with sqlite3.connect(self.dbpath) as db:
            db.execute("DELETE FROM candles WHERE symbol='XAUTUSD' AND t IN (?,?,?)",
                       (START+2*STEP,START+3*STEP,START+4*STEP))
            db.commit()
        before = self.dbpath.read_bytes()
        with sqlite3.connect(self.dbpath) as db:
            report = inspect_window(db, "XAUTUSD", START, START+8*STEP)
        self.assertEqual(report["missing_bar_count"], 3)
        self.assertEqual(len(report["missing_utc_examples"]), 3)
        self.assertIn("missing_broker_bars", report["issues"])
        self.assertEqual(self.dbpath.read_bytes(), before)

    def test_quarantined_bar_not_mislabeled_as_missing(self):
        self.add_candles("BTCUSD")
        with sqlite3.connect(self.dbpath) as db:
            original = db.execute(
                "SELECT symbol,t,o,h,l,c,v FROM candles WHERE symbol='BTCUSD' AND t=?",
                (START+2*STEP,)).fetchone()
            db.execute("DELETE FROM candles WHERE symbol='BTCUSD' AND t=?",
                       (START+2*STEP,))
            db.execute("INSERT INTO candle_quarantine VALUES (?,?,?,?,?,?,?,?)",
                       (*original, "conflicting_historical_refetch"))
            db.commit()
            report = inspect_window(db, "BTCUSD", START, START+8*STEP)
        self.assertEqual(report["quarantined_bar_count"], 1)
        self.assertEqual(report["missing_bar_count"], 0)
        self.assertEqual(len(report["quarantined_utc_examples"]), 1)
        self.assertIn("quarantined_evidence", report["issues"])

    def test_flags_btc_extreme_with_exact_aligned_timestamp(self):
        self.add_candles("BTCUSD")
        with sqlite3.connect(self.dbpath) as db:
            db.execute(
                "UPDATE candles SET h=150000 WHERE symbol='BTCUSD' AND t=?",
                (START+4*STEP,))
            db.commit()
            result = inspect_window(db, "BTCUSD", START, START+8*STEP)
        self.assertEqual(result["suspect_bar_count"], 1)
        self.assertEqual(
            result["suspect_utc_examples"],
            [datetime.fromtimestamp(START+4*STEP,timezone.utc).isoformat()])
        self.assertIn("suspicious_neighbor_extreme", result["issues"])

    def test_report_read_only_and_never_grants_trade(self):
        self.add_candles("BTCUSD")
        self.add_candles("XAUTUSD")
        before = self.dbpath.read_bytes()
        report = inventory_archive(
            self.root, now=datetime(2026,11,1,0,40,tzinfo=timezone.utc))
        self.assertEqual(report["status"], "local_archive_issues_identified")
        self.assertTrue(report["blockers"])  # Previous month intentionally missing
        self.assertFalse(report["archive_mutations"])
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertEqual(self.dbpath.read_bytes(), before)
        self.assertEqual(report["periods"]["BTCUSD_month"]["retained_bars"],8)

    def test_absent_archive_does_not_create_file(self):
        self.dbpath.unlink()
        report = inventory_archive(self.root)
        self.assertEqual(report["blockers"], ["original_archive_missing_or_untrusted"])
        self.assertFalse(self.dbpath.exists())

    def test_invalid_or_oversized_window_is_rejected(self):
        with sqlite3.connect(self.dbpath) as db:
            for start, end in ((START+1, START+STEP), (START,START),
                               (START,START+33*86400)):
                with self.subTest(start=start,end=end):
                    with self.assertRaises(ValueError):
                        inspect_window(db,"BTCUSD",start,end)


if __name__ == "__main__":
    unittest.main()
