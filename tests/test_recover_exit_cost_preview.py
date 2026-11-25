import unittest
from decimal import Decimal
from recover_trading.exit_cost_preview import build,evaluate
class ExitCostTests(unittest.TestCase):
    def cost(self):
        return {"status":"observed","fill_commission":{"status":"observed_subset","samples":4,"observed_commission":"1","observed_turnover":"1000"},"spread":{"median_full_spread_bps":2}}
    def position(self,q):
        return {"entry_price":"100","mark_price":"100","size":q,"bracket_state":"matching_legs_observed","legs":[{"type":"take_profit_order","trigger":"102" if q>0 else "98"},{"type":"stop_loss_order","trigger":"99" if q>0 else "101"}]}
    def test_exact_break_even_both_sides(self):
        for q in (10,-10):
            r=build(self.position(q),self.cost())
            sign=1 if q>0 else -1
            self.assertAlmostEqual(evaluate(Decimal(100),Decimal(r["break_even_exit_fill_price"]),sign,Decimal(".001"))["net_before_funding_bps"],0)
            self.assertAlmostEqual(r["target_scenario"]["gross_return_bps"],200)
            self.assertLess(r["target_scenario"]["illustrative_adverse_half_spread"]["net_before_funding_bps"],r["target_scenario"]["net_before_funding_bps"])
            self.assertEqual(r["remaining_contracts"],"10")
    def test_exact_exit_notional(self):
        self.assertAlmostEqual(build(self.position(10),self.cost())["target_scenario"]["estimated_commission_bps"],20.2)
        self.assertAlmostEqual(build(self.position(-10),self.cost())["target_scenario"]["estimated_commission_bps"],19.8)
    def test_missing_or_invalid_inputs(self):
        self.assertEqual(build(self.position(10),{})["status"],"unavailable")
        self.assertEqual(build(self.position(0),self.cost())["status"],"unavailable")
        p=self.position(10);p["bracket_state"]="unverified"
        self.assertNotIn("target_scenario",build(p,self.cost()))
    def test_no_spread_imputation(self):
        c=self.cost();c.pop("spread")
        self.assertNotIn("illustrative_adverse_half_spread",build(self.position(-10),c)["target_scenario"])
