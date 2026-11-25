import unittest
from recover_trading.strategy_lab import build
class StrategyLabTests(unittest.TestCase):
    def test_catalogue_and_uncertainty(self):
        h={"timestamp":100,"status":"position_management_cycle","coverage":{"evaluable_rules":47,"unavailable_rules":1},"direction_engine":{"votes":{"LONG":[{"id":"B01","frames":["5m"]}],"SHORT":[],"CONFLICT":[]}}}
        r=build("BTCUSD",h,{}, {},101)
        by={x["id"]:x for x in r["rules"]}
        self.assertEqual(len(by),50);self.assertEqual(by["B01"]["state"],"LONG")
        self.assertIn("ema9",by["B01"]["required_inputs"])
        self.assertEqual(by["B20"]["state"],"no_vote_unverified")
        self.assertEqual(by["B17"]["state"],"deferred")
        self.assertEqual(build("BTCUSD",h,{}, {},281)["rules"][0]["state"],"stale_or_unavailable")
    def test_full_coverage_and_registry_fallback(self):
        h={"timestamp":100,"coverage":{"evaluable_rules":47,"unavailable_rules":0},"direction_engine":{"votes":{"LONG":[],"SHORT":[],"CONFLICT":[]}}}
        r=build("XAUTUSD",h,{}, {},100)
        self.assertEqual(len(r["rules"]),50);self.assertEqual(sum(x["state"]=="inactive" for x in r["rules"]),47)
        self.assertEqual(sum(x["state"]=="deferred" for x in r["rules"]),3)
        self.assertIsNone(r["rules"][0]["research"])
