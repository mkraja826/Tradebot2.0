import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from recover_trading.tb2_liquidation_tools import register_liquidation_tools

class MCP:
    def __init__(self): self.tools={}
    def tool(self):
        def add(f): self.tools[f.__name__]=f; return f
        return add

class LiquidationToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.m=MCP()
        register_liquidation_tools(self.m,data_dir=self.root,liquidation_dir=self.root/"ref")
        self.t=self.m.tools

    def test_registration_missing_and_unsupported(self):
        self.assertEqual(set(self.t),{"liquidation_status","liquidation_history","positioning_history","liquidation_ema_backtest","liquidation_forward_validation"})
        self.assertEqual(self.t["liquidation_status"]()["archives"]["events"]["status"],"unavailable_or_invalid")
        self.assertEqual(self.t["liquidation_ema_backtest"]("BTCUSD",0,60,120)["status"],"research_data_unavailable_or_invalid")
        self.assertEqual(self.t["liquidation_status"]("XAUTUSD")["status"],"unavailable")
        self.assertEqual(self.t["liquidation_forward_validation"]()["status"],"research_data_unavailable_or_invalid")
        self.assertEqual(self.t["liquidation_forward_validation"]("XAUTUSD")["status"],"unavailable")
        self.assertFalse((self.root/"ref").exists())
        with self.assertRaises(ValueError): self.t["liquidation_status"]("../")
        with self.assertRaises(ValueError): self.t["liquidation_history"]("BTCUSD",0,60,501)
        with self.assertRaises(ValueError): self.t["liquidation_ema_backtest"]("BTCUSD",0,120,120)

    def test_events_and_pagination(self):
        p=self.root/"ref";p.mkdir();db=p/"events.sqlite"
        with sqlite3.connect(db) as c:
            c.execute("CREATE TABLE events(batch_id,ordinal,event_ms,side,size,bankruptcy_price)")
            c.execute("CREATE TABLE batches(id,received_ms,duplicate_count)")
            c.execute("CREATE TABLE sessions(id,started_ms,subscribed_ms,heartbeat_ms,ended_ms,status)")
            c.execute("INSERT INTO sessions VALUES(1,0,0,1000,NULL,'subscribed')")
            for i,received in enumerate((2000,3000,60000)):
                c.execute("INSERT INTO batches VALUES(?,?,0)",(str(i),received))
                c.execute("INSERT INTO events VALUES(?,0,1000,'LONG','1','100')",(str(i),))
        before=db.read_bytes()
        a=self.t["liquidation_history"]("BTCUSD",0,60,1)
        b=self.t["liquidation_history"]("BTCUSD",0,60,1,a["next_offset"])
        self.assertEqual((a["returned"],b["returned"],b["next_offset"]),(1,1,None))
        self.assertEqual(a["items"][0]["liquidated_position_side"],"LONG")
        self.assertFalse(self.t["liquidation_status"]()["live_health_verified"])
        self.assertEqual(before,db.read_bytes())

    def test_positioning_and_replay_summary(self):
        p=self.root/"ref";p.mkdir();db=p/"positioning.sqlite"
        with sqlite3.connect(db) as c:
            c.execute("CREATE TABLE positioning(source_ms,received_ms,payload)")
            c.execute("INSERT INTO positioning VALUES(1,2,?)",(json.dumps(dict(symbol="BTCUSDT",source_ms=1,received_ms=2,open_interest_btc_both_sides="20")),))
        self.assertEqual(self.t["positioning_history"]("BTCUSD",0,60)["items"][0]["open_interest_btc_both_sides"],"20")
        (p/"hypotheses.sqlite").touch()
        (self.root/"BTCUSD").mkdir();(self.root/"BTCUSD"/"market.sqlite").touch()
        with patch("recover_trading.tb2_liquidation_tools.run",return_value=dict(trades=[],observation_count=0)):
            r=self.t["liquidation_ema_backtest"]("BTCUSD",0,60,120)
        self.assertEqual(r["status"],"no_archived_observations_in_window")
        self.assertNotIn("trades",r)


    def test_forward_snapshot_predates_enrollment(self):
        p=self.root/"ref";p.mkdir()
        (self.root/"BTCUSD").mkdir()
        h=p/"hypotheses.sqlite";m=self.root/"BTCUSD"/"market.sqlite"
        with sqlite3.connect(h) as db:
            db.execute("CREATE TABLE observations(observed_ms,payload)")
            db.execute("INSERT INTO observations VALUES(60000,'{}')")
        with sqlite3.connect(m) as db:
            db.execute("CREATE TABLE samples(symbol,series,stamp,payload)")
            db.execute("INSERT INTO samples VALUES('BTCUSD','candle:1m',0,'{}')")
        before=(h.read_bytes(),m.read_bytes())
        r=self.t["liquidation_forward_validation"]()
        self.assertEqual(r["status"],"snapshot_predates_enrollment")
        self.assertEqual(r["coverage_cutoff"],60)
        self.assertEqual(before,(h.read_bytes(),m.read_bytes()))

    def test_forward_compact_report(self):
        from recover_trading import liquidation_prospective_v6 as v
        p=self.root/"ref";p.mkdir();(self.root/"BTCUSD").mkdir()
        h=p/"hypotheses.sqlite";m=self.root/"BTCUSD"/"market.sqlite"
        with sqlite3.connect(h) as db:
            db.execute("CREATE TABLE observations(observed_ms,payload)")
            db.execute("INSERT INTO observations VALUES(?,'{}')",(v.START*1000,))
        with sqlite3.connect(m) as db:
            db.execute("CREATE TABLE samples(symbol,series,stamp,payload)")
            db.execute("INSERT INTO samples VALUES('BTCUSD','candle:1m',?,'{}')",(v.START-60,))
        import os
        for path in (h,m):os.utime(path,(v.START,v.START))
        with patch("recover_trading.tb2_liquidation_tools.time.time",return_value=v.START+600):
            r=self.t["liquidation_forward_validation"]()
        self.assertEqual(r["status"],"collecting")
        self.assertEqual(r["enrolled"],0)
        self.assertEqual(r["snapshot_lag_seconds"],600)
        self.assertEqual(r["opportunity_ids"],[])
        self.assertEqual(set(r["all_available"]),set(v.POLICIES))

if __name__=="__main__": unittest.main()

