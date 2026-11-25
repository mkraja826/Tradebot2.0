import unittest,sqlite3,json
from recover_trading.forward_validation import initialize,enroll,settle,SCHEMA
from recover_trading.planner_shadow import VERSION
class ForwardTests(unittest.TestCase):
    def test_frozen_cutoff_and_first_packet(self):
        with sqlite3.connect(":memory:") as db:
            t=1800000000;self.assertEqual(initialize(db,t),t);self.assertEqual(initialize(db,t+100),t)
            def p(at,side):return json.dumps({"symbol":"BTCUSD","version":VERSION,"as_of":at,"direction":side})
            enroll(db,"BTCUSD",[p(t-1,"SHORT"),p(t,"LONG"),p(t+1,"SHORT")],t,t+1)
            self.assertEqual(db.execute("SELECT count(*) FROM outcomes").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT DISTINCT side FROM outcomes").fetchone()[0],"LONG")
            enroll(db,"BTCUSD",[p(t+7200,"SHORT")],t,t+7200)
            self.assertEqual(db.execute("SELECT status FROM outcomes WHERE bucket=? AND horizon_s=14400",((t+7200)//7200,)).fetchone()[0],"overlap")
    def test_settlement_requires_closed_exit(self):
        with sqlite3.connect(":memory:") as db:
            t=1800000000;initialize(db,t)
            enroll(db,"BTCUSD",[json.dumps({"symbol":"BTCUSD","version":VERSION,"as_of":t,"direction":"LONG"})],t,t)
            bars={i:{"time":i,"open":100+(i-t)/300,"close":100+(i-t)/300,"high":101+(i-t)/300,"low":99+(i-t)/300,"volume":1} for i in range(t,t+1800,300)}
            settle(db,"BTCUSD",bars,t+1200)
            self.assertEqual(db.execute("SELECT status FROM outcomes WHERE horizon_s=900").fetchone()[0],"pending")
            settle(db,"BTCUSD",bars,t+1500)
            status,net=db.execute("SELECT status,net_bps FROM outcomes WHERE horizon_s=900").fetchone()
            self.assertEqual(status,"observed");self.assertAlmostEqual(net,(104/101-1)*10000-15)
