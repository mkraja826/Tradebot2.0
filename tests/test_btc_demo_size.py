"""Offline policy tests for experimental one/two-contract Delta DEMO sizing."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tradebot.btc_demo_size import evidence_contract_ceiling, strong_directional_setup
from tradebot.btc_autonomous_demo import AutoBTCController
from tradebot.btc_supervised_execution import SupervisedBTCController
from tradebot.fire_budget import entry_budget
from tradebot.fire_risk import FireRiskLimits, RiskRejected, assess_fire_plan


def strong_context():
    return {
        "ema_15m": {"close": 61500, "ema20": 61000, "slope": "rising"},
        "ema_1h": {"close": 61500, "ema20": 60800, "slope": "rising"},
        "session_vwap": 61100,
        "technical_5m": {
            "adx14": {"adx14": 31, "plus_di14": 29, "minus_di14": 13},
            "rsi14": 61,
            "macd_12_26_9": {"histogram": 42},
            "relative_volume20": {"status": "available", "ratio": 1.3},
        },
    }


class DemoSizeTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_strong_two_vs_exploratory_one(self):
        c = strong_context()
        self.assertTrue(strong_directional_setup(c, "LONG"))
        self.assertEqual(evidence_contract_ceiling(c, "LONG"), 2)
        self.assertEqual(evidence_contract_ceiling(c, "WAIT"), 0)
        self.assertEqual(evidence_contract_ceiling(c, "SHORT"), 1)
        c["technical_5m"]["adx14"]["adx14"] = 17
        self.assertEqual(evidence_contract_ceiling(c, "LONG"), 1)

    def test_missing_or_false_market_evidence_downgrades(self):
        for bad in ({}, {"ema_15m": None}, strong_context() | {"technical_5m": {}}):
            with self.subTest(bad=bad):
                self.assertEqual(evidence_contract_ceiling(bad, "LONG"), 1)
        c = strong_context()
        c["ema_1h"]["close"] = None
        self.assertEqual(evidence_contract_ceiling(c, "LONG"), 1)

    def test_autonomous_normalize_never_converts_wait_or_upsizes(self):
        bot=AutoBTCController(self.root / "fire-ops.sqlite")
        strong=strong_context()
        long_plan = {"direction": "LONG", "contracts": 2, "leverage": 5,
                     "stop_loss": "63140", "take_profit": "64000"}
        weak=strong_context()
        weak["technical_5m"]["adx14"]["adx14"] = 12
        self.assertEqual(bot._normalize_plan(long_plan, weak)["contracts"], 1)
        self.assertEqual(bot._normalize_plan(long_plan, strong)["contracts"], 2)
        self.assertEqual(bot._normalize_plan({**long_plan, "contracts": 1}, strong)["contracts"], 1)
        wait = {"direction":"WAIT", "contracts":0, "stop_loss":None,
                "take_profit":None, "leverage":None,
                "thesis":"No safe protected entry"}
        self.assertEqual(bot._normalize_plan(wait, strong), wait)

    def test_two_contracts_still_require_normal_risk_governor(self):
        base = {
            "leverage": "5", "equity_usd": "173.81",
            "contract_value": "0.001", "max_contracts_per_entry": 2,
            "taker_commission_rate": "0.0005",
        }
        quote={"best_bid": "63214", "best_ask":"63214.5"}
        plan = {"direction":"LONG", "contracts":2, "leverage":5,
                "stop_loss":"63140", "take_profit":"64000"}
        with self.assertRaises(RiskRejected):
            assess_fire_plan(plan,base,quote)
        permitted=assess_fire_plan(plan,base,quote,limits=FireRiskLimits(max_contracts=2))
        self.assertTrue(permitted["approved"])
        self.assertEqual(permitted["max_allowed_loss_usd"], str(__import__("decimal").Decimal("173.81") * __import__("decimal").Decimal("0.0025")))
        with self.assertRaises(RiskRejected):
            assess_fire_plan({**plan,"stop_loss":"62800"},base,quote,
                             limits=FireRiskLimits(max_contracts=2))
        with self.assertRaises(RiskRejected):
            assess_fire_plan({**plan,"contracts":3},base,quote,
                             limits=FireRiskLimits(max_contracts=2))

    def test_supervised_broker_cap_stays_one(self):
        ctrl=SupervisedBTCController(self.root / "supervised.sqlite")
        auto=AutoBTCController(self.root / "autonomous.sqlite")
        self.assertEqual(ctrl._hard_contract_cap(),1)
        self.assertEqual(auto._hard_contract_cap(),2)
        self.assertEqual(ctrl._normalize_plan({"direction":"LONG","contracts":3},strong_context())["contracts"],3)

    def test_budget_sizing_cannot_exceed_requested_cap(self):
        class Fake:
            def _request(self,method,path,*,auth=False):
                if path == "/v2/products/BTCUSD":
                    return {"result":{
                        "symbol":"BTCUSD", "id":27, "contract_type":"perpetual_futures",
                        "settling_asset":{"symbol":"USD"}, "notional_type":"vanilla",
                        "initial_margin":"0.5", "contract_value":"0.001",
                        "taker_commission_rate":"0.0005"}}
                return {"result":{"leverage":5,"product_id":27}}
            def wallet_balances(self):
                return {"meta":{"net_equity":"2000"},
                        "balances":[{"asset_symbol":"USD","available_balance":"2000"}]}
        broker=Fake()
        one=entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=1)
        two=entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=2)
        self.assertEqual(one["max_contracts_per_entry"],1)
        self.assertEqual(two["max_contracts_per_entry"],2)
        with self.assertRaises(ValueError):
            entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=3)


if __name__ == "__main__":
    unittest.main()
