import json,sqlite3,unittest
from contextlib import closing
from recover_trading.paired_forward import initialize,enroll,settle,summarize
from recover_trading.reference_strategy import VERSION
class PairedTests(unittest.TestCase):
    def raw(self,t,d="LONG",r="SHORT"):
        return json.dumps({"symbol":"BTCUSD","version":VERSION,"generated":t,"completed":t,
            "as_of":t//300*300,"comparable_rule_frames":49,"matched_demo":{"direction":d},"matched_reference":{"direction":r}})
    def test_frozen_start_and_enrollment_latency(self):
        t=1800000000
        with closing(sqlite3.connect(":memory:")) as db:
            self.assertEqual(initialize(db,t),t);self.assertEqual(initialize(db,t+100),t)
            self.assertFalse(enroll(db,"BTCUSD",self.raw(t-1),t,t+1))
            self.assertFalse(enroll(db,"BTCUSD",self.raw(t+10),t,t+1))
            self.assertTrue(enroll(db,"BTCUSD",self.raw(t),t,t+1))
            self.assertFalse(enroll(db,"BTCUSD",self.raw(t+2),t,t+3))
            self.assertEqual(db.execute("SELECT DISTINCT entry_at FROM pairs").fetchone()[0],t+600)
            self.assertTrue(enroll(db,"BTCUSD",self.raw(t+7200),t,t+7200))
            self.assertEqual(db.execute("SELECT status FROM pairs WHERE bucket=? AND horizon=14400",((t+7200)//7200,)).fetchone()[0],"overlap")
    def test_identical_window_neutral_and_cost(self):
        t=1800000000
        with closing(sqlite3.connect(":memory:")) as db:
            initialize(db,t);enroll(db,"BTCUSD",self.raw(t,"NEUTRAL","LONG"),t,t)
            bars={i:{"time":i,"open":100+(i-t)/300,"close":100+(i-t)/300,"high":101+(i-t)/300,"low":99+(i-t)/300,"volume":1} for i in range(t,t+1800,300)}
            settle(db,"BTCUSD",bars,t+1200)
            self.assertEqual(db.execute("SELECT status FROM pairs WHERE horizon=900").fetchone()[0],"pending")
            settle(db,"BTCUSD",bars,t+1500)
            d,r=db.execute("SELECT demo_net,reference_net FROM pairs WHERE horizon=900").fetchone()
            self.assertEqual(d,0);self.assertAlmostEqual(r,(104/101-1)*10000-15)
            a=summarize([("NEUTRAL","LONG",d,r)])
            self.assertEqual(a["demo_entries"],0);self.assertIsNone(a["demo_win_rate_per_entry"])
            self.assertAlmostEqual(a["mean_reference_minus_demo_bps"],r)
