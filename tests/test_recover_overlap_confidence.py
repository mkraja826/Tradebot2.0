import unittest
from recover_trading.overlap_confidence import score,build,cluster
from recover_trading.planner_shadow import VERSION
from recover_trading.regime import weighted_votes
class ConfidenceTests(unittest.TestCase):
    def p(self,t,long,short,conflict=()):
        g={"LONG":list(long),"SHORT":list(short),"CONFLICT":list(conflict)}
        r={"regime":"mixed","volatility":"normal"}
        totals,_=weighted_votes({k:[{"id":i} for i in v] for k,v in g.items()},r)
        return {"symbol":"BTCUSD","version":VERSION,"as_of":t,"active_rules":g,"regime":r,
            "direction":"LONG" if totals["LONG"]>totals["SHORT"] else "SHORT" if totals["SHORT"]>totals["LONG"] else "NEUTRAL",
            "scores":{k.lower():v/100 for k,v in totals.items()}}
    def test_prior_only_and_discount(self):
        history=[self.p(t*300,["B01","B02"],[]) for t in range(1,21)]
        p=self.p(21*300,["B01","B02"],["B11"])
        r=score("BTCUSD",p,history+[self.p(22*300,["B11"],["B01","B02"])])
        self.assertEqual(r["history_snapshots"],20)
        self.assertEqual(r["baseline_direction"],"LONG")
        self.assertEqual(r["research_direction"],"SHORT")
        self.assertEqual(r["research_scores"]["LONG"],62.5)
        self.assertEqual(r["discounted_rule_count"],1)
    def test_small_sample_no_change(self):
        p=self.p(600,["B01","B02"],[])
        r=score("BTCUSD",p,[self.p(300,["B01","B02"],[])])
        self.assertEqual(r["baseline_scores"],r["research_scores"])
        self.assertEqual(r["discounted_rule_count"],0)
    def test_complete_link_and_conflict(self):
        self.assertEqual(cluster(["B01","B02","B05"],{("B01","B02"),("B02","B05")}),[["B01","B02"],["B05"]])
        p=self.p(600,[],[],["B01"])
        r=score("BTCUSD",p,[])
        self.assertEqual(r["research_direction"],"NEUTRAL")
        self.assertIsNone(r["research_balance"])
    def test_mismatch_and_replay(self):
        p=self.p(300,["B01"],[]);p["scores"]["long"]=0
        self.assertEqual(score("BTCUSD",p,[])["status"],"baseline_reconstruction_mismatch")
        q=build("BTCUSD",[p,self.p(600,["B01"],[])])
        self.assertEqual(q["replay_counts"]["unverified"],1)
        self.assertEqual(q["replay_counts"]["evaluated"],1)
