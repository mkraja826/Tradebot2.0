import unittest
from recover_trading.regime_performance import build,stratify
class RegimePerformanceTests(unittest.TestCase):
    def test_nonoverlap_across_regimes_and_missing_windows(self):
        rows=[("a",0,"missed",None,None,"mixed","high"),("b",600000000,"observed",1500000000,200,"trending","normal"),("c",1200000000,"observed",2100000000,25,"ranging","normal")]
        r={x["regime"]:x for x in stratify(rows,900)}
        self.assertEqual(r["mixed"]["valid_samples"],0)
        self.assertEqual(r["trending"]["raw_counts"]["overlap_excluded"],1)
        self.assertEqual(r["ranging"]["mean_net_bps"],10)
    def test_family_not_double_counted_and_actual_separate(self):
        rows=[("a","B01",900,1000000,"observed",901000000,25,"mixed","high"),("b","B02",900,1000000,"observed",901000000,35,"mixed","high"),("c","G01",900,1000000,"observed",901000000,50,"trending","normal")]
        ep={"decision_id":"d","attribution":"single_recover_entry_order","active_rules":["B01","B02"],"net_before_funding":"5","gross_pnl":"6","fees":"1"}
        r=build("BTCUSD",rows,[ep,ep],{"d":{"symbol":"BTCUSD","direction_engine":{"regime":{"regime":"mixed","volatility":"high"}}}})
        family=[x for x in r["research"] if x["level"]=="family"]
        self.assertEqual(family[0]["valid_samples"],1)
        self.assertEqual(r["actual"][0]["closed_episodes"],1)
        self.assertEqual(r["exact_rule_sets"][0]["rules"],["B01","B02"])
        self.assertEqual(r["observed_regimes"],["mixed"])
    def test_invalid_exit_not_valid_and_unknown_context(self):
        r=stratify([("a",0,"observed",10,100,"bad","bad")],900)[0]
        self.assertEqual(r["regime"],"unknown")
        self.assertEqual(r["valid_samples"],0)
        self.assertIsNone(r["mean_net_bps"])
