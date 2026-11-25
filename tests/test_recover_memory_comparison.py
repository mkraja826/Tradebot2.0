import unittest,sqlite3,json
from recover_trading.memory_comparison import initialize,enroll,settle,prior_experience
class MemoryComparisonTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:");self.addCleanup(self.db.close);initialize(self.db,1000)
    def decision(self,i="a",at=1200):
        return i,at,{"symbol":"BTCUSD","as_of":at,"new_signals":[{"id":"B01"}]},{"action":"trade","side":"sell"}
    def lessons(self):
        return [(1000,{"symbol":"BTCUSD","decision_id":str(i),"direction":"SHORT","active_rules":["B01"],"closed":"1970-01-01T00:10:00Z","net_before_funding":"-1"}) for i in range(3)]
    def test_future_experience_excluded(self):
        l=self.lessons();l[2]=(1200,l[2][1])
        self.assertEqual(len(prior_experience("BTCUSD","SHORT",["B01"],1200,l)),2)
        self.assertTrue(enroll(self.db,"BTCUSD",self.decision(),l,1000,1201))
        self.assertEqual(self.db.execute("SELECT DISTINCT alternative FROM pairs").fetchone()[0],"SHORT")
    def test_pair_is_frozen_and_settled(self):
        self.assertTrue(enroll(self.db,"BTCUSD",self.decision(),self.lessons(),1000,1201))
        self.assertFalse(enroll(self.db,"BTCUSD",self.decision(),[],1000,1202))
        r=self.db.execute("SELECT start,finish,alternative FROM pairs WHERE horizon=900").fetchone()
        self.assertEqual(r,(1500,2400,"NEUTRAL"))
        bars={t:{"time":t,"open":100,"high":102,"low":99,"close":101} for t in range(1500,2400,300)}
        settle(self.db,"BTCUSD",bars,2700)
        self.assertEqual(self.db.execute("SELECT status,baseline_net,alternative_net FROM pairs WHERE horizon=900").fetchone(),("observed",-115.0,0.0))
    def test_pre_protocol_or_wrong_symbol_excluded(self):
        self.assertFalse(enroll(self.db,"BTCUSD",self.decision(at=999),[],1000,1201))
        self.assertFalse(enroll(self.db,"XAUTUSD",self.decision(),[],1000,1201))
    def test_overlap_reserved(self):
        self.assertTrue(enroll(self.db,"BTCUSD",self.decision(),[],1000,1201))
        self.assertTrue(enroll(self.db,"BTCUSD",self.decision("b",4800),[],1000,4801))
        self.assertEqual(self.db.execute("SELECT status FROM pairs WHERE decision_id='b' AND horizon=14400").fetchone()[0],"overlap")
