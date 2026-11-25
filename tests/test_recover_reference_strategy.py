import unittest
from recover_trading.reference_strategy import scan_windows,compare_reports,targets
class ReferenceStrategyTests(unittest.TestCase):
    def test_registry_and_missing_feeds(self):
        for symbol in ("BTCUSD","XAUTUSD"):
            at=1800000000
            r=scan_windows(symbol,at,{})
            c=compare_reports(r,r)
            self.assertEqual(c["comparable_rule_frames"],0)
            self.assertIsNone(c["matched_demo"])
            self.assertEqual(c["implemented_rules"]+len(c["deferred"]),50)
    def test_identical_candle_sources_agree(self):
        at=1800000000
        from tradebot.market_data_v3 import FRAMES
        windows={}
        for frame,count in targets("BTCUSD").items():
            step=FRAMES[frame];end=at//step*step
            windows[frame]=[{"time":t,"open":p,"close":p,"high":p+1,"low":p-1,"volume":10} for i,t in enumerate(range(end-count*step,end,step)) for p in [100+i/10]]
        r=scan_windows("BTCUSD",at,windows)
        c=compare_reports(r,r)
        self.assertGreater(c["comparable_rule_frames"],0)
        self.assertEqual(c["comparison_counts"].get("different",0),0)
        self.assertEqual(c["matched_demo"],c["matched_reference"])
        self.assertGreater(c["comparison_counts"]["both_unavailable"],0)

    def test_cutoff_uses_latest_stored_closed_candle(self):
        import sqlite3
        from contextlib import closing
        from recover_trading.reference_strategy import matched_cutoff
        t=1800000000
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE samples(symbol TEXT,series TEXT,stamp INTEGER)")
            db.executemany("INSERT INTO samples VALUES(?,?,?)",[("BTCUSD","candle:5m",t-600),("BTCUSD","candle:5m",t),("XAUTUSD","candle:5m",t-300)])
            self.assertEqual(matched_cutoff(db,"BTCUSD",t+5),t-300)
            self.assertEqual(matched_cutoff(db,"XAUTUSD",t+5),t)
