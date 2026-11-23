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

    def test_guideline_percentages_are_not_contract_assignment(self):
        for tier, fraction in (("small","0.05"),("medium","0.20"),
                               ("large","0.40")):
            evidence=size_guideline_evidence(
                {"contracts":7,"leverage":20,"size_tier":tier},
                self.preview,account="GOLD")
            self.assertEqual(evidence["selected_contracts"],7)
            self.assertEqual(evidence["target_equity_notional_fraction"],fraction)
            self.assertEqual(evidence["estimated_notional_usd"],"25.55")
            self.assertEqual(evidence["margin_cap_fraction"],"0.20")

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

    def test_model_quantity_caps_are_still_separate(self):
        self.assertEqual(FIXED_LEVERAGE,20)
        self.assertEqual(BTC_DEMO_CAP,6)
        self.assertEqual(GOLD_DEMO_CAP,64)


if __name__=="__main__":
    unittest.main()