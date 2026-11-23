"""AI-selected quantity stays unchanged; gross stop <= target is a hard gate.

The gate uses signed executable best-ask for LONG, best-bid for SHORT,
including the final quote recheck, not a stale model-created midpoint.
All tests offline. No order is sent and no credentials are required.
"""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradebot.btc_autonomous_demo import AutoBTCController
from tradebot.gold_autonomous_controller import AutoGoldController
from tradebot.fire_risk import FireRiskLimits, RiskRejected, assess_fire_plan


def budget():
    return {"leverage":"20","equity_usd":"10","contract_value":"0.001",
            "max_contracts_per_entry":6,"taker_commission_rate":"0.0005"}


def quote():
    return {"best_bid":"3600","best_ask":"3600"}


class AutonomousQuantityAndDistanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.btc=AutoBTCController(self.root/"btc-isolated"/"fire-ops.sqlite")
        self.gold=AutoGoldController(self.root/"gold-isolated"/"fire-xaut.sqlite")

    def test_both_models_retain_own_quantity_not_indicator_tier(self):
        for label,bot in (("BTC",self.btc),("GOLD",self.gold)):
            for number in (1,2,3,4,5,6):
                with self.subTest(market=label,quantity=number):
                    proposal={"direction":"LONG","leverage":20,"contracts":number,
                              "stop_loss":"3590","take_profit":"3610"}
                    self.assertEqual(bot._normalize_plan(proposal,{}),proposal)
                    self.assertEqual(bot._entry_sizing_record()
                                     ["sizing_evidence"]["selected_contracts"],number)
                    self.assertEqual(bot._entry_sizing_record()
                                     ["sizing_evidence"]["model_proposed_contracts"],number)
                    self.assertNotIn("tier",bot._entry_sizing_record()["sizing_evidence"])
            oversized={"direction":"LONG","leverage":20,"contracts":7,
                       "stop_loss":"3590","take_profit":"3610"}
            self.assertEqual(bot._normalize_plan(oversized,{})["contracts"],7)
            self.assertEqual(bot._entry_sizing_record(),{})
            with self.assertRaises(RiskRejected):
                bot._assess_risk(oversized,budget(),quote())

    def test_equal_gross_stop_and_target_distance_accepted_long_and_short(self):
        for bot in (self.btc,self.gold):
            for side,stop,tp in (("LONG","3590","3610"),
                                 ("SHORT","3610","3590")):
                for count in (1,6):
                    with self.subTest(market=bot.symbol,side=side,quantity=count):
                        plan={"direction":side,"contracts":count,"leverage":20,
                              "stop_loss":stop,"take_profit":tp}
                        result=bot._assess_risk(plan,budget(),quote())
                        self.assertTrue(result["approved"])
                        self.assertEqual(Decimal(result["gross_stop_distance"]),
                                         Decimal(result["gross_target_distance"]))
                        self.assertEqual(result["minimum_gross_reward_risk"],"1")

    def test_shorter_target_distance_is_rejected_for_both_directions(self):
        for bot in (self.btc,self.gold):
            for side,stop,tp in (("LONG","3590","3609.99"),
                                 ("SHORT","3610","3590.01")):
                with self.subTest(market=bot.symbol,side=side):
                    plan={"direction":side,"contracts":2,"leverage":20,
                          "stop_loss":stop,"take_profit":tp}
                    with self.assertRaisesRegex(
                            RiskRejected,"Stop distance exceeds allowed reward distance"):
                        bot._assess_risk(plan,budget(),quote())

    def test_final_executable_quote_move_rejects_previous_valid_levels(self):
        for bot in (self.btc,self.gold):
            for side,stop,tp,shift in (
                    ("LONG","3590","3610",{"best_bid":"3601.99",
                                           "best_ask":"3602"}),
                    ("SHORT","3610","3590",{"best_bid":"3598",
                                            "best_ask":"3598.01"})):
                with self.subTest(market=bot.symbol,side=side):
                    plan={"direction":side,"contracts":2,"leverage":20,
                          "stop_loss":stop,"take_profit":tp}
                    self.assertTrue(bot._assess_risk(plan,budget(),quote())["approved"])
                    with self.assertRaisesRegex(
                            RiskRejected,"Stop distance exceeds allowed reward distance"):
                        bot._assess_risk(plan,budget(),shift)

    def test_legacy_risk_policy_not_implicitly_changed(self):
        plan={"direction":"LONG","contracts":1,"leverage":20,
              "stop_loss":"3590","take_profit":"3609.99"}
        limits=FireRiskLimits(equity_risk_fraction=Decimal("0.0025"),
                              minimum_net_reward_risk=Decimal("1"),
                              max_contracts=6)
        # Our new gross rule is opt-in only for the autonomous controllers:
        # legacy default retains its own net reward / equity caps, not this one.
        self.assertIsNone(limits.minimum_gross_reward_risk)
        with self.assertRaises(ValueError):
            FireRiskLimits(minimum_gross_reward_risk=Decimal("0.5"))


if __name__=="__main__":
    unittest.main()
