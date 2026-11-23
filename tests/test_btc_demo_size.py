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

    def test_small_medium_big_evidence_tiers(self):
        c = strong_context()
        self.assertTrue(strong_directional_setup(c, "LONG"))
        self.assertEqual(evidence_contract_ceiling(c, "LONG"), 3)
        self.assertEqual(evidence_contract_ceiling(c, "WAIT"), 0)
        self.assertEqual(evidence_contract_ceiling(c, "SHORT"), 1)
        c["technical_5m"]["adx14"]["adx14"] = 21
        self.assertEqual(evidence_contract_ceiling(c, "LONG"), 2)
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
        long_plan = {"direction": "LONG", "contracts": 3, "leverage": 5,
                     "stop_loss": "63205", "take_profit": "64000"}
        weak=strong_context()
        weak["technical_5m"]["adx14"]["adx14"] = 12
        medium=strong_context()
        medium["technical_5m"]["adx14"]["adx14"] = 21
        self.assertEqual(bot._normalize_plan(long_plan, weak)["contracts"], 1)
        self.assertEqual(bot._normalize_plan(long_plan, medium)["contracts"], 2)
        self.assertEqual(bot._normalize_plan(long_plan, strong)["contracts"], 3)
        self.assertEqual(bot._normalize_plan({**long_plan, "contracts": 1}, strong)["contracts"], 1)
        self.assertEqual(bot._entry_sizing_record()["sizing_evidence"]["tier"], "exploratory_one")
        oversized=bot._normalize_plan({**long_plan,"contracts":4}, strong)
        self.assertEqual(oversized["contracts"],4)  # remains invalid: never cap into validity
        wait = {"direction":"WAIT", "contracts":0, "stop_loss":None,
                "take_profit":None, "leverage":None,
                "thesis":"No safe protected entry"}
        self.assertEqual(bot._normalize_plan(wait, strong), wait)

    def test_three_contracts_still_require_normal_risk_governor(self):
        base = {
            "leverage": "5", "equity_usd": "173.81",
            "contract_value": "0.001", "max_contracts_per_entry": 3,
            "taker_commission_rate": "0.0005",
        }
        quote={"best_bid": "63214", "best_ask":"63214.5"}
        plan = {"direction":"LONG", "contracts":3, "leverage":5,
                "stop_loss":"63205", "take_profit":"64000"}
        with self.assertRaises(RiskRejected):
            assess_fire_plan(plan,base,quote)
        permitted=assess_fire_plan(plan,base,quote,limits=FireRiskLimits(max_contracts=3))
        self.assertTrue(permitted["approved"])
        self.assertEqual(permitted["max_allowed_loss_usd"], str(__import__("decimal").Decimal("173.81") * __import__("decimal").Decimal("0.0025")))
        with self.assertRaises(RiskRejected):
            assess_fire_plan({**plan,"stop_loss":"62800"},base,quote,
                             limits=FireRiskLimits(max_contracts=2))
        with self.assertRaises(RiskRejected):
            assess_fire_plan({**plan,"contracts":4},base,quote,
                             limits=FireRiskLimits(max_contracts=2))

    def test_autonomous_risk_budget_scales_with_independent_tier(self):
        from decimal import Decimal
        bot=AutoBTCController(self.root / "auto-risk.sqlite")
        base={
            "leverage":"5", "equity_usd":"173.81",
            "contract_value":"0.001", "max_contracts_per_entry":3,
            "taker_commission_rate":"0.0005",
        }
        quote={"best_bid":"63214", "best_ask":"63214.5"}
        template={"direction":"LONG", "leverage":5,
                  "stop_loss":"63205", "take_profit":"64000"}
        for qty,risk_fraction in ((1,"0.0025"),(2,"0.0035"),(3,"0.005")):
            with self.subTest(qty=qty):
                assessed=bot._assess_risk({**template,"contracts":qty},base,quote)
                self.assertTrue(assessed["approved"])
                self.assertEqual(
                    Decimal(assessed["max_allowed_loss_usd"]),
                    Decimal("173.81")*Decimal(risk_fraction))
        with self.assertRaises(RiskRejected):
            bot._assess_risk({**template,"contracts":3,
                              "stop_loss":"62800"},base,quote)
        with self.assertRaises(RiskRejected):
            bot._assess_risk({**template,"contracts":4},base,quote)

    def test_supervised_broker_cap_stays_one(self):
        ctrl=SupervisedBTCController(self.root / "supervised.sqlite")
        auto=AutoBTCController(self.root / "autonomous.sqlite")
        self.assertEqual(ctrl._hard_contract_cap(),1)
        self.assertEqual(auto._hard_contract_cap(),3)
        self.assertEqual(ctrl._normalize_plan({"direction":"LONG","contracts":3},strong_context())["contracts"],3)

    def test_three_contract_offline_broker_post_has_full_brackets(self):
        from tradebot.fire_execution import FireDemoController
        from test_fire_execution import FakeDemo, snapshot, seed_demo_equity
        from pathlib import Path

        class ScopedDemo(FireDemoController):
            def _hard_contract_cap(self):
                return 3
            def _assess_risk(self, plan, budget, quote):
                return assess_fire_plan(
                    plan, budget, quote,
                    limits=FireRiskLimits(
                        max_contracts=3,
                        equity_risk_fraction=__import__("decimal").Decimal("0.005")))
            def _decision_context(self, exchange, collected, midpoint):
                return {}
            def _historical_levels(self, collected, midpoint):
                return {"periods":{
                    name:{"quality_status":"provisionally_valid"}
                    for name in ("day", "previous_day", "week",
                                 "previous_week", "month", "previous_month")}}

        path = self.root / "triple-btc.sqlite"
        demo = FakeDemo()
        demo.leverage = 6  # 3 contracts fit the initial broker margin ceiling
        seed_demo_equity(path, "173.81")
        plan = {
            "direction":"LONG", "contracts":3, "leverage":6,
            "stop_loss":"63205", "take_profit":"64000",
            "thesis":"Verified strong trend (offline simulated)"
        }
        bot = ScopedDemo(
            path,enabled=True,exchange_factory=lambda:demo,
            snapshot_loader=snapshot,
            probe=lambda routes,load: {"results":{"fire":{"decision":plan}}},
            spawn=lambda task:task(),pause=lambda seconds:None)
        ok,_=bot.start()
        self.assertTrue(ok)
        receipt=bot.snapshot()
        self.assertEqual(receipt["status"],"protected_active", receipt.get("reason_code"))
        self.assertTrue(receipt["orders_submitted"])
        self.assertTrue(receipt["protection_verified"])
        self.assertTrue(receipt["liquidation_verified"])
        self.assertEqual(len(demo.requests),1)
        order_method,order_path,payload=demo.requests[0]
        self.assertEqual((order_method,order_path),("POST","/v2/orders"))
        self.assertEqual(payload["size"],3)
        self.assertEqual(payload["bracket_stop_loss_price"],"63205")
        self.assertEqual(payload["bracket_take_profit_price"],"64000")
        self.assertEqual(len(demo.active_orders),2)
        self.assertEqual([entry["size"] for entry in demo.active_orders],[3,3])

    def test_scope_two_only_admitted_in_unattended_demo(self):
        from tradebot.ai import PlanError
        from tradebot.fire_probe import instruction_for_snapshot
        features = strong_context()
        features["atr_5m"] = 150
        features["historical_levels"] = {
            "source":"original_delta_demo_24h_5m_local_only",
            "strategy_history_version":"btc-demo-recent24h-v1",
            "periods":{"last_24h":{
                "bars":288,"expected":288,"quality_status":"provisionally_valid"}},
        }
        features["local_market_screen"] = {
            "status":"passed",
            "independent_price_verified":False,
            "trade_authorized":False,
            "external_spot_reference":{
                "status":"spot_reference_corroborated",
                "independent_perpetual_trade_print_verified":False,
                "trade_authorized":False,
            },
        }
        scope = {
            "strategy_history_version":"btc-demo-recent24h-v1",
            "max_contracts_per_entry":3,
            "attached_stop_loss_and_take_profit_required":True,
            "unattended_demo_mode":True,
            "one_attempt_operator_supervision_required":False,
            "max_new_order_attempts_per_utc_day":48,
        }
        obj = {
            "environment":"delta-india-demo",
            "core":{"ticker":{"symbol":"BTCUSD"}},
            "fire_execution_scope":scope,
            "indicators":features,
        }
        prompt = instruction_for_snapshot(obj)
        self.assertIn("at most three contracts per attempt",prompt)
        self.assertIn("Direction must be LONG or SHORT",prompt)
        self.assertNotIn("Direction must be WAIT, LONG or SHORT",prompt)
        with self.assertRaises(PlanError):
            instruction_for_snapshot({
                **obj,"fire_execution_scope":{
                    **scope,"unattended_demo_mode":None}})
        with self.assertRaises(PlanError):
            instruction_for_snapshot({
                **obj,"fire_execution_scope":{
                    **scope,"max_contracts_per_entry":4}})

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
        three=entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=3)
        self.assertEqual(one["max_contracts_per_entry"],1)
        self.assertEqual(two["max_contracts_per_entry"],2)
        self.assertEqual(three["max_contracts_per_entry"],3)
        with self.assertRaises(ValueError):
            entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=4)


if __name__ == "__main__":
    unittest.main()
