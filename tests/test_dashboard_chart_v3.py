from contextlib import closing
import unittest,sqlite3,json,tempfile
from pathlib import Path
from tradebot.dashboard_chart_v3 import chart,profiles
class ChartTests(unittest.TestCase):
 def test_closed_gap_and_scope(self):
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)
        with closing(sqlite3.connect(p/"market-v3.sqlite")) as db, db:
            db.execute("CREATE TABLE samples(symbol,series,stamp,payload)")
            for t in (600,1200,1500):
                db.execute("INSERT INTO samples VALUES(?,?,?,?)",("BTCUSD","candle:5m",t,json.dumps(dict(time=t,open=10,high=12,low=9,close=11,volume=3))))
        a=chart(p,"BTCUSD","5m",now=1501)
        self.assertEqual([b["time"] for b in a["bars"]],[600,1200])
        self.assertEqual(a["gaps"],1)
        self.assertFalse(a["execution_authorized"])
        with self.assertRaises(ValueError):chart(p,"../../etc/passwd","5m",now=1501)
 def test_profiles_latest_costs(self):
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);g=dict(frame="5m",side="LONG",samples=2,sample_status="insufficient_sample",scenario="fixed",horizon=60,cost_scenarios={"10":{"mean_pct":-.1,"positive":1,"raw":"excluded"}})
        r=dict(mode="strategy_performance_advisory",execution_authorized=False,strategy_eligibility_changed=False,checked_at=1200,markets={"BTCUSD":{"profiles":[dict(rule_id="B01",name="Example",historical=[dict(start=100,end=200,scenarios=[g]),dict(start=200,end=300,scenarios=[g,dict(g,horizon=15)])])]}})
        (p/"strategy-profiles-v3.json").write_text(json.dumps(r))
        a=profiles(p,"BTCUSD",now=1201)
        self.assertEqual(len(a["rows"]),1);self.assertEqual(a["rows"][0]["start"],200)
        self.assertNotIn("raw",a["rows"][0]["costs"]["10"])
        self.assertFalse(a["execution_authorized"])
