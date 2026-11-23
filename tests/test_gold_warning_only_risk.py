"""Gold's discretionary thresholds warn like BTC; brokerage safety never does."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradebot.fire_risk import FireRiskLimits,RiskRejected,assess_fire_plan
from tradebot.gold_autonomous_controller import AutoGoldController


class GoldWarningOnlyRiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot=AutoGoldController(
            Path(self.tmp.name)/"gold-isolated"/"fire-xaut.sqlite")
        self.budget={
            "leverage":"20","equity_usd":"10",
            "contract_value":"0.001",
            "max_contracts_per_entry":6,
            "taker_commission_rate":"0.0005",
        }
        self.quote={"best_bid":"3599.99","best_ask":"3600.00"}
        self.plan={"direction":"LONG","contracts":6,"leverage":20,
                   "stop_loss":"3570.00","take_profit":"3630.00"}

    def test_gold_20x_equal_gross_target_and_stop_warns_on_net_quality(self):
        x=self.bot._assess_risk(self.plan,self.budget,self.quote)
        self.assertTrue(x["approved"])
        self.assertEqual(x["policy_version"],"gold-demo-chart-stop-v1")
        self.assertEqual(x["trade_quality_policy"],"warnings_only_autonomous_demo")
        self.assertFalse(x["equity_loss_ceiling_enabled"])
        self.assertIsNone(x["max_allowed_loss_usd"])
        self.assertGreater(Decimal(x["estimated_loss_fraction_of_equity"]),
                           Decimal("0.0025"))
        self.assertEqual(Decimal(x["gross_stop_distance"]),Decimal("30"))
        self.assertEqual(Decimal(x["gross_target_distance"]),Decimal("30"))
        self.assertEqual(x["minimum_gross_reward_risk"],"1")
        self.assertGreater(Decimal(x["estimated_net_target_reward_usd"]),0)
        self.assertLess(Decimal(x["expected_net_reward_risk"]),Decimal("1"))
        self.assertIn("net_reward_risk_below_1_5",x["quality_warnings"])
        self.assertNotIn("net_target_reward_after_costs_nonpositive",x["quality_warnings"])

    def test_gold_small_medium_large_same_warning_policy(self):
        for contracts in (1,2,3,6):
            with self.subTest(contracts=contracts):
                x=self.bot._assess_risk(
                    {**self.plan,"contracts":contracts},self.budget,self.quote)
                self.assertTrue(x["approved"])
                self.assertEqual(x["selected_leverage"],20)
                self.assertIsNone(x["max_allowed_loss_usd"])

    def test_bad_margin_price_and_liquidation_gap_still_block(self):
        for plan,budget in (
            ({**self.plan,"contracts":7},self.budget),
            (self.plan,{**self.budget,"max_contracts_per_entry":1}),
            ({**self.plan,"leverage":21},self.budget),
            ({**self.plan,"stop_loss":"3620"},self.budget),
            ({**self.plan,"stop_loss":"3400"},self.budget),
            (self.plan,{**self.budget,"leverage":"5"}),
        ):
            with self.subTest(plan=plan,budget=budget):
                with self.assertRaises(RiskRejected):
                    self.bot._assess_risk(plan,budget,self.quote)

    def test_btc_and_normal_fire_policy_unchanged(self):
        btc=FireRiskLimits(equity_risk_fraction=None,
            minimum_net_reward_risk=None,max_contracts=6,
            version="btc-demo-chart-stop-v4")
        self.assertTrue(assess_fire_plan(self.plan,self.budget,
                                        self.quote,limits=btc)["approved"])
        with self.assertRaises(ValueError):
            FireRiskLimits(equity_risk_fraction=None,
                minimum_net_reward_risk=None,max_contracts=6,
                version="unknown-strategy")
        with self.assertRaises(ValueError):
            FireRiskLimits(equity_risk_fraction=None,
                minimum_net_reward_risk=None,max_contracts=1,
                version="gold-demo-chart-stop-v1")
        with self.assertRaises(RiskRejected):
            assess_fire_plan(self.plan,self.budget,self.quote,
                limits=FireRiskLimits(max_contracts=6))


if __name__=="__main__":
    unittest.main()
