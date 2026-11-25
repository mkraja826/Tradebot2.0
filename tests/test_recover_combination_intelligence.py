import unittest
from recover_trading.combination_intelligence import overlap,cohorts
from recover_trading.planner_shadow import VERSION
class CombinationTests(unittest.TestCase):
    def p(self,t,long,short,conflict=[]):
        return {"symbol":"BTCUSD","version":VERSION,"as_of":t,"active_rules":{"LONG":long,"SHORT":short,"CONFLICT":conflict}}
    def test_bucket_and_conflict(self):
        r=overlap("BTCUSD",[self.p(300,["B01","B01","B02"],[]),self.p(301,["B01"],["B02"]),self.p(600,["B01"],["B02"]),self.p(900,["B01"],[],["B02"]),self.p(1200,["B01"],[])])
        a=r["pairs"][0]
        self.assertEqual(r["sampled_packets"],4)
        self.assertEqual((a["same_direction"],a["opposed_direction"],a["conflict_involved"]),(1,1,1))
        self.assertEqual(a["jaccard"],.75)
    def row(self,i,rule,t,status="observed",v=100):
        return i,rule,t,900,"LONG",100,status,t+900000000,101,v
    def test_shared_quote_not_double_counted(self):
        rows=[self.row("a","B01",0),self.row("b","B01",0),self.row("c","B02",0),self.row("d","B01",600000000),self.row("e","B02",600000000)]
        r=cohorts("BTCUSD",rows);p=r["pair_horizons"][0]
        self.assertEqual(r["joint_cohorts"],2)
        self.assertEqual(p["valid_nonoverlap_samples"],1)
        self.assertAlmostEqual(p["mean_net_bps"],85)
    def test_different_times_and_inconsistent_paths(self):
        r=cohorts("BTCUSD",[self.row("a","B01",0),self.row("b","B02",1)])
        self.assertEqual(r["joint_cohorts"],0)
        r=cohorts("BTCUSD",[self.row("a","B01",0),self.row("b","B02",0,v=200)])
        self.assertEqual(r["invalid_or_incomplete_cohorts"],1)
        self.assertIsNone(r["pair_horizons"][0]["mean_net_bps"])
