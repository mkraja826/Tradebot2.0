from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from tradebot.candle_archive import CandleArchive, DAY, STEP, swing_levels
from tradebot.market_integrity import suspect_candle_times


class CandleArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/"history.sqlite"
        self.archive = CandleArchive(self.path)
        self.end = int(datetime(2026,3,2,0,5,tzinfo=timezone.utc).timestamp())
        self.floor = self.end-65*DAY
        self.exchange = Mock()
        def read(method,path,params=None):
            if path.startswith("/v2/products"):
                return {"result":{"symbol":"BTCUSD","launch_time":self.floor}}
            return {"result":[dict(time=t,open=3,high=4,low=2,close=3,volume=1)
                    for t in range(params["start"],params["end"]+1,STEP)]}
        self.exchange._request.side_effect = read

    def test_restart_and_calendar_boundaries(self):
        self.archive.sync_page(self.exchange,"BTCUSD",self.end)
        archive = CandleArchive(self.path)
        while archive.sync_page(self.exchange,"BTCUSD",self.end):
            pass
        snapshot = archive.levels("BTCUSD",self.end,3)
        self.assertTrue(snapshot["scanned_to_launch"])
        self.assertEqual(snapshot["periods"]["previous_month"]["bars"],28*288)
        self.assertEqual(snapshot["periods"]["previous_week"]["bars"],7*288)
        self.assertEqual(snapshot["periods"]["week"]["bars"],1)
        self.assertEqual(snapshot["periods"]["day"]["high"],4)
        self.assertIsNone(archive.levels("XAUTUSD",self.end,3)["periods"]["day"]["high"])
        archive.sync_page(self.exchange,"BTCUSD",self.end+STEP)
        with archive.connect() as db:
            db.execute("DELETE FROM candles WHERE t=?",(self.end,))
        self.assertIsNone(archive.levels("BTCUSD",self.end+STEP,3)["periods"]["day"]["high"])

    def test_extreme_candle_quarantined_not_used_in_level(self):
        bad_at = self.end - 6 * STEP
        original = self.exchange._request.side_effect
        def modified(method,path,params=None):
            result = original(method,path,params)
            if path == "/v2/history/candles":
                for row in result["result"]:
                    if row["time"] == bad_at:
                        row["high"] = 1000
            return result
        self.exchange._request.side_effect = modified
        self.archive.sync_page(self.exchange, "BTCUSD", self.end)
        with self.archive.connect() as db:
            record = db.execute(
                "SELECT h,reason FROM candle_quarantine WHERE symbol=? AND t=?",
                ("BTCUSD",bad_at)).fetchone()
            self.assertEqual(record,(1000,"extreme_neighbor_dislocation"))
        level = self.archive.levels("BTCUSD",self.end,3)["periods"]["previous_day"]
        self.assertIsNone(level["high"])
        self.assertEqual(level["quality_status"],"quarantined")

    def test_imported_bad_extreme_is_blocked_but_retained(self):
        self.archive.sync_page(self.exchange, "BTCUSD", self.end)
        bad_at = self.end - 5 * STEP
        with self.archive.connect() as db:
            db.execute("UPDATE candles SET l=0.1 WHERE symbol=? AND t=?",
                       ("BTCUSD",bad_at))
            db.commit()
        level = self.archive.levels("BTCUSD",self.end,3)["periods"]["previous_day"]
        self.assertEqual(level["quality_status"],"suspicious_extreme")
        self.assertIsNone(level["low"])
        with self.archive.connect() as db:
            self.assertEqual(db.execute(
                "SELECT l FROM candles WHERE symbol=? AND t=?",
                ("BTCUSD",bad_at)).fetchone()[0],0.1)

    def test_closed_refetch_revision_quarantines_original_instead_of_replacing(self):
        self.archive.sync_page(self.exchange, "BTCUSD", self.end)
        disputed = self.end - 5 * STEP
        base_read = self.exchange._request.side_effect

        def revised(method, path, params=None):
            result = base_read(method, path, params)
            if path == "/v2/history/candles":
                for candle in result["result"]:
                    if candle["time"] == disputed:
                        candle["high"] = 4.5  # valid, non-extreme revision
            return result

        self.exchange._request.side_effect = revised
        self.archive.sync_page(self.exchange, "BTCUSD", self.end + STEP)
        with self.archive.connect() as db:
            old = db.execute(
                "SELECT h,reason FROM candle_quarantine WHERE symbol=? AND t=?",
                ("BTCUSD", disputed)).fetchone()
            current = db.execute(
                "SELECT h FROM candles WHERE symbol=? AND t=?",
                ("BTCUSD", disputed)).fetchone()
        self.assertEqual(old, (4, "conflicting_historical_refetch"))
        self.assertIsNone(current)
        self.assertEqual(
            self.archive.levels("BTCUSD", self.end + STEP, 3)
            ["periods"]["previous_day"]["quality_status"], "quarantined")

    def test_identical_closed_refetch_remains_usable(self):
        self.archive.sync_page(self.exchange, "BTCUSD", self.end)
        self.archive.sync_page(self.exchange, "BTCUSD", self.end + STEP)
        with self.archive.connect() as db:
            count = db.execute(
                "SELECT count(*) FROM candle_quarantine WHERE symbol='BTCUSD'"
            ).fetchone()[0]
            value = db.execute(
                "SELECT h FROM candles WHERE symbol=? AND t=?",
                ("BTCUSD", self.end - 5 * STEP)).fetchone()
        self.assertEqual(count, 0)
        self.assertEqual(value, (4,))

    def test_conflicting_duplicate_candle_quarantined_before_history_admission(self):
        original_read = self.exchange._request.side_effect
        disputed = self.end - 5 * STEP

        def duplicated(method, path, params=None):
            result = original_read(method, path, params)
            if path == "/v2/history/candles":
                row = next(row for row in result["result"] if row["time"] == disputed)
                result["result"].append({**row, "high": 4.5})
            return result

        self.exchange._request.side_effect = duplicated
        self.archive.sync_page(self.exchange, "BTCUSD", self.end)
        with self.archive.connect() as db:
            reason = db.execute(
                "SELECT reason FROM candle_quarantine WHERE symbol=? AND t=?",
                ("BTCUSD", disputed)).fetchone()
            active = db.execute(
                "SELECT 1 FROM candles WHERE symbol=? AND t=?",
                ("BTCUSD", disputed)).fetchone()
        self.assertEqual(reason, ("conflicting_duplicate",))
        self.assertIsNone(active)

    def test_normal_neighbor_ranges_not_flagged(self):
        rows = [("BTCUSD",i*300,3,4,2,3,1) for i in range(5)]
        self.assertEqual(suspect_candle_times(rows),{})

    def test_swings_wait_for_confirmation(self):
        bars=[(i*300,8 if i//3==2 else 6,2 if i//3==2 else 4) for i in range(15)]
        self.assertIsNone(swing_levels(bars[:-1],5)["15m"]["support"])
        swing=swing_levels(bars,5)["15m"]
        self.assertEqual(swing["support"]["price"],2)
        self.assertEqual(swing["resistance"]["confirmed_at"],4500)
