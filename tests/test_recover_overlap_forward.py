import unittest,sqlite3
from recover_trading.overlap_forward import initialize,enroll,settle,summarize
from recover_trading.planner_shadow import VERSION
from recover_trading.regime import weighted_votes
class OverlapForwardTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:");self.addCleanup(self.db.close);initialize(self.db,6000)
    def p(self,t,long,short):
        g={"LONG":long,"SHORT":short,"CONFLICT":[]};r={"regime":"mixed","volatility":"normal"}
        total,_=weighted_votes({k:[{"id":i} for i in v] for k,v in g.items()},r)
        return {"symbol":"BTCUSD","version":VERSION,"as_of":t,"active_rules":g,"regime":r,"direction":"LONG" if total["LONG"]>total["SHORT"] else "SHORT" if total["SHORT"]>total["LONG"] else "NEUTRAL","scores":{k.lower():v/100 for k,v in total.items()}}
    def test_freeze_and_future_window(self):
        history=[self.p(t*300,["B01","B02"],[]) for t in range(1,21)]
        p=self.p(6300,["B01","B02"],["B11"])
        self.assertTrue(enroll(self.db,"BTCUSD",p,history,6000,6301))
        self.assertFalse(enroll(self.db,"BTCUSD",p,[],6000,6302))
        row=self.db.execute("SELECT baseline,alternative,entry_at,exit_at FROM pairs WHERE horizon=900").fetchone()
        self.assertEqual(row,("LONG","SHORT",6900,7800))
        bars={t:{"time":t,"open":100,"high":102,"low":99,"close":101} for t in range(6900,7800,300)}
        settle(self.db,"BTCUSD",bars,8099)
        self.assertEqual(self.db.execute("SELECT status FROM pairs WHERE horizon=900").fetchone()[0],"pending")
        settle(self.db,"BTCUSD",bars,8100)
        self.assertEqual(self.db.execute("SELECT status,baseline_net,alternative_net FROM pairs WHERE horizon=900").fetchone(),("observed",85.,-115.))
    def test_no_stale_or_preprotocol(self):
        self.assertFalse(enroll(self.db,"BTCUSD",self.p(5999,["B01"],[]),[],6000,6001))
        self.assertFalse(enroll(self.db,"BTCUSD",self.p(6300,["B01"],[]),[],6000,6481))
    def test_neutral_and_overlap(self):
        self.assertTrue(enroll(self.db,"BTCUSD",self.p(6300,[],[]),[],6000,6301))
        self.assertTrue(enroll(self.db,"BTCUSD",self.p(9900,["B01"],[]),[],6000,9901))
        self.assertEqual(self.db.execute("SELECT status FROM pairs WHERE source_at=9900 AND horizon=14400").fetchone()[0],"overlap")
        bars={t:{"time":t,"open":100,"high":101,"low":99,"close":100} for t in range(6900,7800,300)}
        settle(self.db,"BTCUSD",bars,8100)
        self.assertEqual(self.db.execute("SELECT baseline_net,alternative_net FROM pairs WHERE source_at=6300 AND horizon=900").fetchone(),(0.,0.))
    def test_summary_disagreement(self):
        r=summarize([("LONG","LONG",10,10),("LONG","NEUTRAL",-20,0)])
        self.assertEqual(r["disagreements"],1);self.assertEqual(r["mean_difference_bps"],10);self.assertEqual(r["disagreement_mean_difference_bps"],20)
