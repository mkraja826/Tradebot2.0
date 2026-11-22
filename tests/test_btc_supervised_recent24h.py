"""Offline original-archive integrity tests for optional 24h BTC pilot context."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tradebot.btc_supervised_recent24h import inspect_recent_btc_window

NOW = datetime(2026, 11, 22, 17, 30, tzinfo=timezone.utc)
END = int(NOW.timestamp()) // 300 * 300
FIRST = END - 288 * 300


class RecentBTCWindowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / "delta-demo-candles.sqlite"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE candles(
                    symbol TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,v REAL,
                    PRIMARY KEY(symbol,t));
                CREATE TABLE candle_quarantine(
                    symbol TEXT,t INTEGER,reason TEXT,
                    PRIMARY KEY(symbol,t));
                CREATE TABLE coverage(symbol TEXT,newest_scan INTEGER);
            """)
            db.execute("INSERT INTO coverage VALUES ('BTCUSD',?)", (END,))
            db.executemany(
                "INSERT INTO candles VALUES ('BTCUSD',?,?,?,?,?,?)",
                [(FIRST + i*300, 100.0,101.0,99.0,100.0,2.0)
                 for i in range(288)])
            db.commit()

    def check(self):
        before = self.path.read_bytes()
        result = inspect_recent_btc_window(self.root, now=NOW)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["independently_verified_btc_perpetual_prices"])
        self.assertFalse(result["original_monthly_anomalies_resolved"])
        self.assertFalse(result["broker_order_mutations"])
        return result

    def test_contiguous_24h_is_just_candidate_not_order_authority(self):
        r = self.check()
        self.assertEqual(r["status"], "recent24h_local_candidate_only")
        self.assertEqual(r["retained_bars"], 288)
        self.assertEqual(r["first_utc"],
                         datetime.fromtimestamp(FIRST, timezone.utc).isoformat())
        self.assertTrue(r["complete_contiguous_24h"])

    def test_missing_five_minute_bar_blocks(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM candles WHERE t=?", (FIRST + 1800,))
        self.assertEqual(self.check()["reason"],
                         "missing_or_misaligned_recent_5m_bars")

    def test_local_extreme_price_is_suspect(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE candles SET h=900 WHERE t=?",
                       (FIRST + 3000,))
        self.assertEqual(self.check()["reason"],
                         "recent_btc_price_dislocation")

    def test_quarantined_bar_blocks(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO candle_quarantine VALUES ('BTCUSD',?,'bad')",
                       (FIRST + 3600,))
        self.assertEqual(self.check()["reason"],
                         "recent_btc_quarantine_present")

    def test_stale_archive_collection_blocks(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE coverage SET newest_scan=?",
                       (END - 300,))
        self.assertEqual(self.check()["reason"],
                         "recent_archive_collection_not_current")

    def test_malformed_data_blocks(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE candles SET l=-1 WHERE t=?",
                       (FIRST + 3000,))
        self.assertEqual(self.check()["reason"],
                         "original_archive_integrity_or_schema_unverified")

    def test_missing_database_does_not_create(self):
        self.path.unlink()
        self.assertEqual(self.check()["reason"],
                         "original_archive_unavailable")
        self.assertFalse(self.path.exists())

    def test_normal_fire_six_period_gate_untouched(self):
        src = (Path(__file__).resolve().parents[1] /
               "src/tradebot/fire_execution.py").read_text()
        self.assertIn('required = ("day", "previous_day", "week", "previous_week",',
                      src)
        self.assertNotIn("btc_supervised_recent24h", src)
        module = (Path(__file__).resolve().parents[1] /
                  "src/tradebot/btc_supervised_recent24h.py").read_text()
        self.assertIn("return 2  # A local data subset cannot authorize", module)


if __name__ == "__main__":
    unittest.main()
