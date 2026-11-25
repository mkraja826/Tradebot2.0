import unittest
from recover_trading.strategy_evidence import build,summarize
class StrategyEvidenceTests(unittest.TestCase):
    def test_nonoverlap_selection_includes_missing(self):
        rows=[("a",1000000,"missed",None,None),("b",2000000,"observed",902000000,100),("c",1201000000,"observed",2101000000,20)]
        r=summarize(rows,900)
        self.assertEqual(r["raw_counts"]["overlap_excluded"],1)
        self.assertEqual(r["valid_samples"],1)
        self.assertEqual(r["mean_net_bps"],5)
    def test_catalog_and_exact_rule_set(self):
        ep={"decision_id":"a","active_rules":["B02","B01","B01"],"gross_pnl":"5","fees":"1","net_before_funding":"4"}
        b=build("BTCUSD",[],{"recent_episodes":[ep]})
        g=build("XAUTUSD",[],{})
        self.assertEqual(len(b["rules"]),50)
        self.assertEqual(len(g["rules"]),50)
        self.assertEqual(b["implemented"]+g["implemented"],95)
        self.assertEqual(b["exact_entry_rule_sets"][0]["rules"],["B01","B02"])
        self.assertEqual(b["exact_entry_rule_sets"][0]["net_before_funding"],"4")
