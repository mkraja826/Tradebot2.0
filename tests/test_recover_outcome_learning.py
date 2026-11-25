import unittest,sqlite3
from recover_trading.outcome_learning import initialize,enroll,settle,measure
class LearningTests(unittest.TestCase):
    def test_freeze_and_followup(self):
        db=sqlite3.connect(":memory:");self.addCleanup(db.close);initialize(db)
        ep={"decision_id":"a","opened":"1970-01-01T00:01:00Z","closed":"1970-01-01T00:05:01Z","direction":"SHORT","attribution":"single_recover_entry_order","net_before_funding":"5"}
        p={"status":"reconciled_subset","recent_episodes":[ep]};r={"status":"observed","recent":[{"id":"a","outcome":"closed_reconciled","net_before_funding":"5"}]}
        self.assertEqual(enroll(db,"BTCUSD",p,r,{},400),1)
        self.assertEqual(enroll(db,"BTCUSD",p,r,{},2000),0)
        self.assertEqual(db.execute("SELECT timing FROM followups WHERE horizon=900").fetchone()[0],"prospective_window")
        bars={t:{"time":t,"open":100,"high":101,"low":98,"close":99} for t in (600,900,1200)}
        settle(db,"BTCUSD",bars,1800)
        self.assertEqual(db.execute("SELECT status FROM followups WHERE horizon=900").fetchone()[0],"observed")
        self.assertEqual(measure(bars,600,1500,"SHORT")["gross_directional_price_return_bps"],100)
        self.assertIsNone(measure(bars,600,1800,"SHORT"))
    def test_unattributed_and_missing(self):
        db=sqlite3.connect(":memory:");self.addCleanup(db.close);initialize(db)
        self.assertEqual(enroll(db,"XAUTUSD",{"status":"reconciled_subset","recent_episodes":[{"decision_id":None}]},{"status":"observed"}, {},1000),0)
