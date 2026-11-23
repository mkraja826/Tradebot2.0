"""Offline policy tests for small, medium, and dynamic large DEMO sizing."""
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
        self.assertEqual(evidence_contract_ceiling(c, "LONG"), 6)
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

    def test_autonomous_preserves_model_quantity_across_indicator_strengths(self):
        bot=AutoBTCController(self.root / "fire-ops.sqlite")
        strong=strong_context()
        proposal={"direction":"LONG", "contracts":6,"leverage":5,
                  "stop_loss":"63205","take_profit":"64000"}
        weak=strong_context()
        weak["technical_5m"]["adx14"]["adx14"]=12
        medium=strong_context()
        medium["technical_5m"]["adx14"]["adx14"]=21
        for evidence in (weak, medium, strong, {}):
            with self.subTest(evidence=evidence):
                self.assertEqual(bot._normalize_plan(proposal,evidence),proposal)
                record=bot._entry_sizing_record()["sizing_evidence"]
                self.assertEqual(record["selected_contracts"],6)
                self.assertEqual(record["model_proposed_contracts"],6)
                self.assertEqual(record["model_selected_leverage"],5)
                self.assertFalse(record["quantity_auto_reduced"])
                self.assertNotIn("tier",record)
        for selected in (1,2,3,4,5,6):
            choice={**proposal,"contracts":selected}
            self.assertEqual(bot._normalize_plan(choice,weak)["contracts"],selected)
        # A proposal outside the independent hard demo cap is NOT resized
        # into a valid order. The execution/risk layer must reject it.
        oversized=bot._normalize_plan({**proposal,"contracts":7},strong)
        self.assertEqual(oversized["contracts"],7)
        self.assertEqual(bot._entry_sizing_record(),{})
        wait={"direction":"WAIT","contracts":0,
              "stop_loss":None,"take_profit":None,"leverage":None,
              "thesis":"No safe protected entry"}
        self.assertEqual(bot._normalize_plan(wait,strong),wait)

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

    def test_autonomous_chart_stop_exceeds_old_percent_caps_all_sizes(self):
        from decimal import Decimal
        bot = AutoBTCController(self.root / "auto-risk.sqlite")
        budget = {
            "leverage": "5", "equity_usd": "173.81",
            "contract_value": "0.001", "max_contracts_per_entry": 6,
            "taker_commission_rate": "0.0005",
        }
        quote = {"best_bid": "63214", "best_ask": "63214.5"}
        # A chart-selected stop 714.5 USD below entry exceeds every legacy
        # size-tier percent threshold, but preserves valid margin and R:R.
        plan = {"direction": "LONG", "leverage": 5,
                "stop_loss": "62500", "take_profit": "65000"}
        for size, prior_cap in ((1, "0.0025"), (2, "0.0035"), (3, "0.005"),
                                (4, "0.005"), (6, "0.005")):
            with self.subTest(contracts=size):
                result = bot._assess_risk({**plan, "contracts": size},
                                          budget, quote)
                self.assertTrue(result["approved"])
                self.assertEqual(result["policy_version"], "btc-demo-chart-stop-v4")
                self.assertFalse(result["equity_loss_ceiling_enabled"])
                self.assertIsNone(result["max_allowed_loss_usd"])
                self.assertGreater(
                    Decimal(result["estimated_loss_fraction_of_equity"]),
                    Decimal(prior_cap))
                self.assertGreater(
                    Decimal(result["estimated_loss_including_costs_usd"]), 0)
                self.assertGreaterEqual(
                    Decimal(result["expected_net_reward_risk"]), Decimal("1.5"))
        # A malformed size, insufficient broker margin or unprotected stop
        # still cannot be approved merely because equity percent is uncapped.
        with self.assertRaises(RiskRejected):
            bot._assess_risk({**plan, "contracts": 7}, budget, quote)
        with self.assertRaises(RiskRejected):
            bot._assess_risk({**plan, "contracts": 6},
                             {**budget, "max_contracts_per_entry": 2}, quote)
        with self.assertRaises(RiskRejected):
            bot._assess_risk({**plan, "contracts": 6, "stop_loss": "63500"},
                             budget, quote)
        weak = bot._assess_risk(
            {**plan, "contracts": 6, "take_profit": "63929"}, budget, quote)
        self.assertTrue(weak["approved"])
        self.assertIn("net_reward_risk_below_1_5", weak["quality_warnings"])

    def test_autonomous_demo_weak_net_reward_risk_is_warning_only(self):
        from decimal import Decimal
        bot = AutoBTCController(self.root / "soft-risk-demo.sqlite")
        budget = {
            "leverage": "5", "equity_usd": "173.81",
            "contract_value": "0.001", "max_contracts_per_entry": 6,
            "taker_commission_rate": "0.0005",
        }
        quote = {"best_bid": "63214", "best_ask": "63214.5"}
        baseline = {
            "direction": "LONG", "contracts": 1, "leverage": 5,
            "stop_loss": "62500", "take_profit": "63929",
        }
        evaluated = bot._assess_risk(baseline, budget, quote)
        self.assertTrue(evaluated["approved"])
        self.assertEqual(evaluated["trade_quality_policy"],
                         "warnings_only_autonomous_demo")
        self.assertIn("net_reward_risk_below_1_5", evaluated["quality_warnings"])
        self.assertLess(Decimal(evaluated["expected_net_reward_risk"]), Decimal("1.5"))
        self.assertIsNone(evaluated["max_allowed_loss_usd"])
        # Once the new gross exit-distance rule is enabled, a closer target
        # than the SL distance must be rejected even on isolated DEMO.
        with self.assertRaisesRegex(
                RiskRejected, "Stop distance exceeds allowed reward distance"):
            bot._assess_risk({**baseline, "take_profit": "63225"},
                             budget, quote)
        # Unlike experimental DEMO, normal FIRE still enforces its own
        # minimum net reward/risk and cannot opt into warning-only.
        with self.assertRaises(RiskRejected):
            assess_fire_plan(
                baseline, budget, quote,
                limits=FireRiskLimits(max_contracts=6))
        with self.assertRaises(ValueError):
            FireRiskLimits(minimum_net_reward_risk=None)
        with self.assertRaises(ValueError):
            FireRiskLimits(equity_risk_fraction=Decimal("0.0025"),
                           minimum_net_reward_risk=None,
                           version="btc-demo-chart-stop-v4", max_contracts=6)

    def test_chart_stop_policy_opt_in_does_not_undercut_normal_fire(self):
        from decimal import Decimal
        with self.assertRaises(ValueError):
            FireRiskLimits(equity_risk_fraction=None)
        with self.assertRaises(ValueError):
            FireRiskLimits(equity_risk_fraction=None, max_contracts=6)
        with self.assertRaises(ValueError):
            FireRiskLimits(equity_risk_fraction=None,
                           version="btc-demo-chart-stop-v4", max_contracts=1)
        base = {
            "leverage": "20", "equity_usd": "173.81",
            "contract_value": "0.001", "max_contracts_per_entry": 6,
            "taker_commission_rate": "0.0005",
        }
        quote = {"best_bid": "63214", "best_ask": "63214.5"}
        # An extremely distant stop is still rejected if it crosses the
        # theoretical liquidation cushion, even with no percent-loss ceiling.
        distant = {"direction": "LONG", "leverage": 20, "contracts": 6,
                   "stop_loss": "60000", "take_profit": "75000"}
        bot = AutoBTCController(self.root / "chart-guard.sqlite")
        with self.assertRaisesRegex(RiskRejected, "liquidation"):
            bot._assess_risk(distant, base, quote)
        self.assertEqual(
            FireRiskLimits().equity_risk_fraction, Decimal("0.0025"))

    def test_supervised_broker_cap_stays_one(self):
        ctrl=SupervisedBTCController(self.root / "supervised.sqlite")
        auto=AutoBTCController(self.root / "autonomous.sqlite")
        self.assertEqual(ctrl._hard_contract_cap(),1)
        self.assertEqual(auto._hard_contract_cap(),6)
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

    def test_six_contract_broker_order_keeps_dual_attached_protection(self):
        from decimal import Decimal
        from tradebot.fire_execution import FireDemoController
        from test_fire_execution import FakeDemo, snapshot, seed_demo_equity

        class SixContractMock(FireDemoController):
            def _hard_contract_cap(self):
                return 6
            def _assess_risk(self, plan, budget, quote):
                return assess_fire_plan(
                    plan, budget, quote, limits=FireRiskLimits(
                        max_contracts=6, equity_risk_fraction=Decimal("0.005")))
            def _decision_context(self, exchange, collected, midpoint):
                return {}
            def _historical_levels(self, collected, midpoint):
                return {"periods": {
                    period: {"quality_status": "provisionally_valid"}
                    for period in ("day", "previous_day", "week",
                                   "previous_week", "month", "previous_month")}}

        path=self.root/"six-contracts.sqlite"
        demo=FakeDemo()
        demo.leverage=20
        seed_demo_equity(path,"173.81")
        plan = {
            "direction": "LONG", "contracts": 6, "leverage": 20,
            "stop_loss": "63205", "take_profit": "64000",
            "thesis": "Six-contract strong evidence offline fixture",
        }
        bot=SixContractMock(
            path,enabled=True,exchange_factory=lambda:demo,
            snapshot_loader=snapshot,
            probe=lambda roles,load: {"results":{"fire":{"decision":plan}}},
            spawn=lambda callback:callback(),pause=lambda seconds:None)
        ok,_=bot.start()
        self.assertTrue(ok)
        receipt=bot.snapshot()
        self.assertEqual(receipt["status"],"protected_active",
                         receipt.get("reason_code"))
        self.assertTrue(receipt["orders_submitted"])
        self.assertTrue(receipt["protection_verified"])
        self.assertTrue(receipt["liquidation_verified"])
        self.assertEqual(len(demo.requests),1)
        self.assertEqual(demo.requests[0][2]["size"],6)
        self.assertEqual(demo.requests[0][2]["bracket_stop_loss_price"],"63205")
        self.assertEqual(demo.requests[0][2]["bracket_take_profit_price"],"64000")
        self.assertEqual(sorted(x["size"] for x in demo.active_orders),[6,6])
        self.assertEqual(receipt["selected_leverage"],20)
        self.assertGreater(
            Decimal(receipt["sizing_estimate"]["nominal_initial_margin_usd"]),0)
        self.assertLessEqual(
            Decimal(receipt["risk_assessment"]["estimated_loss_including_costs_usd"]),
            Decimal("173.81")*Decimal("0.005"))

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
            "max_contracts_per_entry":6,
            "attached_stop_loss_and_take_profit_required":True,
            "unattended_demo_mode":True,
            "one_attempt_operator_supervision_required":False,
            "daily_attempt_cap_enabled":False,
        }
        obj = {
            "environment":"delta-india-demo",
            "core":{"ticker":{"symbol":"BTCUSD"}},
            "fire_execution_scope":scope,
            "indicators":features,
        }
        prompt = instruction_for_snapshot(obj)
        self.assertIn("Up to six contracts",prompt)
        self.assertIn("no daily model-attempt-count cap",prompt)
        self.assertNotIn("48 attempts",prompt)
        self.assertIn("chart", prompt)
        self.assertIn("stop_loss", prompt)
        self.assertIn("no fixed per-trade percentage-loss cap", prompt)
        self.assertIn("Direction must be LONG or SHORT",prompt)
        self.assertNotIn("Direction must be WAIT, LONG or SHORT",prompt)
        with self.assertRaises(PlanError):
            instruction_for_snapshot({
                **obj,"fire_execution_scope":{
                    **scope,"unattended_demo_mode":None}})
        with self.assertRaises(PlanError):
            instruction_for_snapshot({
                **obj,"fire_execution_scope":{
                    **scope,"max_contracts_per_entry":7}})
        with self.assertRaises(PlanError):
            instruction_for_snapshot({
                **obj,"fire_execution_scope":{
                    **scope,"max_new_order_attempts_per_utc_day":48}})
        with self.assertRaises(PlanError):
            instruction_for_snapshot({
                **obj,"fire_execution_scope":{
                    **scope,"daily_attempt_cap_enabled":True}})

    def test_gpt6_leverage_changes_affordable_quantity_without_bypassing_broker(self):
        class Broker:
            def _request(self, method, path, *, auth=False):
                if path == "/v2/products/BTCUSD":
                    return {"result": {
                        "symbol": "BTCUSD", "id": 27,
                        "contract_type": "perpetual_futures",
                        "settling_asset": {"symbol": "USD"},
                        "notional_type": "vanilla", "initial_margin": "0.5",
                        "contract_value": "0.001",
                        "taker_commission_rate": "0.0005"}}
                return {"result": {"leverage": 5, "product_id": 27}}
            def wallet_balances(self):
                return {"meta": {"net_equity": "200"},
                        "balances": [{"asset_symbol": "USD",
                                     "available_balance": "200"}]}
        broker = Broker()
        ctrl = AutoBTCController(self.root / "large-margin.sqlite")
        preview = ctrl._model_entry_budget(broker, 27, "63214.5")
        self.assertTrue(preview["capacity_preview_only"])
        self.assertEqual(preview["capacity_preview_leverage"], 20)
        self.assertEqual(preview["broker_leverage"], "5")
        self.assertEqual(preview["max_contracts_per_entry"], 6)
        actual_five = ctrl._entry_budget(broker, 27, "63214.5",
                                        planned_leverage=5)
        actual_ten = ctrl._entry_budget(broker, 27, "63214.5",
                                       planned_leverage=10)
        self.assertLess(actual_five["max_contracts_per_entry"], 6)
        self.assertGreater(actual_ten["max_contracts_per_entry"],
                           actual_five["max_contracts_per_entry"])
        plan = {"direction": "LONG", "contracts": 6, "leverage": 5,
                "stop_loss": "63205", "take_profit": "64000"}
        quote = {"best_bid": "63214", "best_ask": "63214.5"}
        with self.assertRaises(RiskRejected):
            ctrl._assess_risk(plan, actual_five, quote)
        # Even when the 20x preview advertises capacity, the final broker
        # budget at GPT-6's chosen leverage is the authority.
        with self.assertRaises(RiskRejected):
            ctrl._assess_risk(plan, preview, quote)

    def test_sizing_receipt_preserves_gpt6_choice_without_raw_model_output(self):
        from tradebot.fire_execution import FireTradeStore
        store = FireTradeStore(self.root / "size-receipt.sqlite")
        press = store.reserve()
        self.assertIsInstance(press, str)
        record = {"tier": "strong_dynamic", "model_proposed_contracts": 5,
                  "selected_contracts": 5, "model_selected_leverage": 12,
                  "evidence_contract_ceiling": 6,
                  "policy": "btc-demo-evidence-size-v3"}
        saved = store.update(press, "preflight", sizing_evidence=record,
                             selected_leverage=12)
        self.assertEqual(saved["sizing_evidence"], record)
        self.assertEqual(saved["selected_leverage"], 12)

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
        six=entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=6)
        self.assertEqual(one["max_contracts_per_entry"],1)
        self.assertEqual(two["max_contracts_per_entry"],2)
        self.assertEqual(three["max_contracts_per_entry"],3)
        self.assertEqual(six["max_contracts_per_entry"],6)
        with self.assertRaises(ValueError):
            entry_budget(broker,"BTCUSD",27,"63214.5",max_contracts_limit=7)


if __name__ == "__main__":
    unittest.main()
