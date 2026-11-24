"""GPT-6 and DeepSeek own tier/quantity decisions; 20x remains fixed."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradebot.btc_autonomous_demo import AutoBTCController
from tradebot.gold_autonomous_controller import AutoGoldController
from tradebot.fire_risk import RiskRejected
from tradebot.isolated_tier_sizing import (
    size_guideline_evidence, GOLD_DEMO_CAP, BTC_DEMO_CAP, FIXED_LEVERAGE)


class IndependentTierChoiceTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.preview={"equity_usd":"475","notional_per_contract_usd":"3.65",
                      "max_contracts_per_entry":64,"leverage":"20"}

    def test_model_selected_tiers_and_contracts_are_never_rewritten(self):
        for ctrl, account in (
                (AutoBTCController(self.root/"btc-isolated"/"test.sqlite"),"BTC"),
                (AutoGoldController(self.root/"gold-isolated"/"test.sqlite"),"GOLD")):
            ctrl._tier_preview=self.preview
            max_qty=6 if account=="BTC" else 64
            for qty, tier in ((1,"small"),(2,"medium"),(max_qty,"large")):
                proposal={"direction":"LONG","contracts":qty,"leverage":20,
                          "stop_loss":"100","take_profit":"200",
                          "size_tier":tier}
                self.assertEqual(ctrl._normalize_plan(proposal,{}),proposal)
                record=ctrl._entry_sizing_record()["sizing_evidence"]
                self.assertEqual(record["selected_contracts"],qty)
                self.assertEqual(record["model_selected_size_tier"],tier)
                self.assertFalse(record["quantity_auto_adjusted"])
                self.assertTrue(record["tiers_are_guidance_only"])

    def test_hundred_dollar_account_margin_math(self):
        for tier, margin, notional in (
            ("small", "5.00", "100.00"),
            ("medium", "20.00", "400.00"),
            ("large", "40.00", "800.00")):
            e = size_guideline_evidence(
                {"size_tier": tier, "contracts": 1, "leverage": 20},
                {"equity_usd": "100", "notional_per_contract_usd": "100"},
                account="BTC")
            self.assertEqual(e["target_margin_usd"], margin)
            self.assertEqual(e["target_notional_usd"], notional)

    def test_guideline_percentages_are_not_contract_assignment(self):
        for tier, fraction in (("small","0.05"),("medium","0.20"),
                               ("large","0.40")):
            evidence=size_guideline_evidence(
                {"contracts":7,"leverage":20,"size_tier":tier},
                self.preview,account="GOLD")
            self.assertEqual(evidence["selected_contracts"],7)
            self.assertEqual(evidence["target_equity_margin_fraction"],fraction)
            self.assertEqual(evidence["target_equity_notional_fraction"],
                             str(__import__("decimal").Decimal(fraction)*20))
            self.assertEqual(evidence["estimated_notional_usd"],"25.55")
            self.assertEqual(evidence["margin_cap_fraction"],"0.40")

    def test_wrong_account_or_invalid_size_never_gets_evidence(self):
        self.assertRaises(ValueError,size_guideline_evidence,
                          {"contracts":1},self.preview,account="MAIN")
        self.assertEqual(size_guideline_evidence(
            {"contracts":0},self.preview,account="BTC"),{})

    def test_non20_leverage_cannot_pass_either_model_risk_gate(self):
        for cls, label in ((AutoBTCController, "btc"), (AutoGoldController, "gold")):
            ctrl=cls(self.root / (label+"-isolated") / "risk.sqlite")
            with self.subTest(label=label):
                with self.assertRaisesRegex(RiskRejected, "fixed 20x"):
                    ctrl._assess_risk(
                        {"direction":"LONG","contracts":1,"leverage":10,
                         "stop_loss":"100","take_profit":"150"}, {}, {})

    def test_signed_budget_40pct_opt_in_keeps_legacy_20pct(self):
        from tradebot.fire_budget import entry_budget
        class Broker:
            def _request(self, method, path, *, auth=False):
                if path == "/v2/products/BTCUSD":
                    return {"result":{"symbol":"BTCUSD","id":27,
                        "contract_type":"perpetual_futures",
                        "settling_asset":{"symbol":"USD"},
                        "notional_type":"vanilla","initial_margin":"0.5",
                        "contract_value":"1",
                        "taker_commission_rate":"0.0005"}}
                return {"result":{"leverage":20,"product_id":27}}
            def wallet_balances(self):
                return {"meta":{"net_equity":"100"},
                        "balances":[{"asset_symbol":"USD",
                                     "available_balance":"100"}]}
        broker = Broker()
        legacy = entry_budget(broker,"BTCUSD",27,"100",
                              planned_leverage=20,max_contracts_limit=96)
        isolated = entry_budget(broker,"BTCUSD",27,"100",
                              planned_leverage=20,max_contracts_limit=96,
                              margin_share=Decimal("0.40"))
        self.assertEqual(legacy["margin_budget_usd"],"20.00")
        self.assertEqual(isolated["margin_budget_usd"],"40.00")
        self.assertEqual(legacy["max_contracts_per_entry"],4)
        self.assertEqual(isolated["max_contracts_per_entry"],8)
        with self.assertRaises(ValueError):
            entry_budget(broker,"BTCUSD",27,"100",max_contracts_limit=1,
                         margin_share=Decimal("0.40"))

    def test_model_quantity_caps_are_still_separate(self):
        self.assertEqual(FIXED_LEVERAGE,20)
        self.assertEqual(BTC_DEMO_CAP,96)
        self.assertEqual(GOLD_DEMO_CAP,1200)


if __name__=="__main__":
    unittest.main()
