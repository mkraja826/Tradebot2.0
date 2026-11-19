from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from tradebot.candle_archive import CandleArchive, DAY, STEP, swing_levels


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

    def test_swings_wait_for_confirmation(self):
        bars=[(i*300,8 if i//3==2 else 6,2 if i//3==2 else 4) for i in range(15)]
        self.assertIsNone(swing_levels(bars[:-1],5)["15m"]["support"])
        swing=swing_levels(bars,5)["15m"]
        self.assertEqual(swing["support"]["price"],2)
        self.assertEqual(swing["resistance"]["confirmed_at"],4500)
