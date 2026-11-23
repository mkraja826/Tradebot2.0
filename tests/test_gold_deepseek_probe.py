"""DeepSeek Gold-only model choice; no broker POST authority."""
import json
import unittest
from datetime import datetime, timezone, timedelta

from tradebot.ai import PlanError
from tradebot.fire_probe import ROLES
from tradebot.gold_deepseek_probe import (
    GOLD_MODEL, GOLD_ROLES, run_gold_deepseek_probe,
    validate_gold_isolated_snapshot,
)


def gold_snapshot():
    return {
        "environment": "delta-india-demo",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "core": {
            "best_bid": "4120.0",
            "best_ask": "4121.0",
            "ticker": {
                "symbol": "XAUTUSD", "contract_type": "perpetual_futures",
                "tick_size": "0.1", "product_id": 923,
            },
        },
        "fire_execution_scope": {
            "expected_isolated_demo_subaccount": "GOLD",
            "signed_subaccount_isolated_verified": True,
            "broker_account_flat_verified": True,
            "attached_stop_loss_and_take_profit_required": True,
            "market_data_verified": True,
            "trade_authorized": False,
            "max_contracts_per_entry": 1,
        },
    }


class GoldDeepSeekTests(unittest.TestCase):
    def test_distinct_selected_models(self):
        self.assertEqual(ROLES, {"fire": "tb-gpt-6"})
        self.assertEqual(GOLD_ROLES, {"fire": "tb-deepseek-v4-1-flash"})
        self.assertNotEqual(ROLES, GOLD_ROLES)

    def test_wrong_market_or_unverified_account_blocks_before_paid_ai(self):
        def client():
            self.fail("No model client allowed before scope proof")
        for broken in (
            {"environment": "delta-india-live"},
            {"core": {**gold_snapshot()["core"],
                      "ticker": {**gold_snapshot()["core"]["ticker"],
                                 "symbol": "BTCUSD"}}},
            {"fire_execution_scope": {**gold_snapshot()["fire_execution_scope"],
                                      "broker_account_flat_verified": False}},
            {"fire_execution_scope": {**gold_snapshot()["fire_execution_scope"],
                                      "market_data_verified": False}},
            {"fire_execution_scope": {**gold_snapshot()["fire_execution_scope"],
                                      "expected_isolated_demo_subaccount": "BTC"}},
        ):
            with self.subTest(broken=broken):
                snap={**gold_snapshot(), **broken}
                with self.assertRaises(PlanError):
                    run_gold_deepseek_probe(GOLD_ROLES, lambda:snap,client)
        with self.assertRaises(PlanError):
            run_gold_deepseek_probe(ROLES,gold_snapshot,client)

    def test_stale_or_tampered_broker_quote_blocks_before_model(self):
        for bad in (
            {"collected_at": (datetime.now(timezone.utc)
                 - timedelta(minutes=3)).isoformat()},
            {"collected_at": "2026-11-23T00:00:00"},
            {"core": {**gold_snapshot()["core"],"best_ask":"4100.0"}},
            {"core": {**gold_snapshot()["core"],"ticker":{
                **gold_snapshot()["core"]["ticker"],"tick_size":"0"}}},
        ):
            snap={**gold_snapshot(),**bad}
            with self.subTest(bad=bad):
                with self.assertRaises(PlanError):
                    validate_gold_isolated_snapshot(snap)

    def test_off_tick_model_stop_rejected_without_broker_order(self):
        class Client:
            last_request_id=None
            def _call(self,url,*,body=None,timeout):
                if body is None:return {"data":[{"id":GOLD_MODEL}]}
                return {"choices":[{"finish_reason":"stop",
                     "message":{"content":json.dumps({
                        "direction":"LONG","leverage":3,"contracts":1,
                        "stop_loss":4100.15,"take_profit":4160.0,
                        "thesis":"tick alignment test"})}}]}
        report=run_gold_deepseek_probe(GOLD_ROLES,gold_snapshot,Client)
        self.assertIn("error",report["results"]["fire"])
        self.assertNotIn("decision",report["results"]["fire"])
        self.assertFalse(report["trade_authorized"])

    def test_single_deepseek_gold_completion_with_valid_json(self):
        paid=[]
        class Client:
            last_request_id="demotest"
            def _call(self,url,*,body=None,timeout):
                if body is None:
                    return {"data":[{"id": GOLD_MODEL}]}
                paid.append(body)
                return {"choices":[{
                    "finish_reason":"stop",
                    "message":{"content":json.dumps({
                        "direction":"LONG","leverage":3,"contracts":1,
                        "stop_loss":4100,"take_profit":4160,
                        "thesis":"Signed Gold-specific chart evidence."})},
                }]}
        report=run_gold_deepseek_probe(GOLD_ROLES,gold_snapshot,Client)
        self.assertEqual(len(paid),1)
        self.assertEqual(paid[0]["model"],GOLD_MODEL)
        self.assertNotIn("response_format",paid[0])
        self.assertIn("XAUTUSD",paid[0]["messages"][0]["content"])
        self.assertIn("Gold",paid[0]["messages"][0]["content"])
        self.assertEqual(report["results"]["fire"]["model"],GOLD_MODEL)
        self.assertEqual(report["results"]["fire"]["decision"]["direction"],"LONG")
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["broker_order_mutations"])

    def test_oversize_or_malformed_response_cannot_return_valid_decision(self):
        for answer in ({"direction":"SHORT","leverage":4,"contracts":2,
                        "stop_loss":4150,"take_profit":4100,"thesis":"oversized"},
                       {"direction":"LONG","leverage":3,"contracts":1,
                        "stop_loss":4140,"take_profit":4190,
                        "thesis":"invalid direction stop"}):
            class Client:
                last_request_id=None
                def _call(self,url,*,body=None,timeout):
                    if body is None:return {"data":[{"id":GOLD_MODEL}]}
                    return {"choices":[{"finish_reason":"stop",
                        "message":{"content":json.dumps(answer)}}]}
            report=run_gold_deepseek_probe(GOLD_ROLES,gold_snapshot,Client)
            self.assertIn("error",report["results"]["fire"])
            self.assertNotIn("decision",report["results"]["fire"])
            self.assertFalse(report["trade_authorized"])

    def test_wait_still_creates_no_order_permit(self):
        class Client:
            last_request_id=None
            def _call(self,url,*,body=None,timeout):
                if body is None:return {"data":[{"id":GOLD_MODEL}]}
                return {"choices":[{"finish_reason":"stop",
                     "message":{"content":json.dumps({
                         "direction":"WAIT","contracts":0,
                         "leverage":None,"stop_loss":None,
                         "take_profit":None,
                         "thesis":"Gold archive incomplete"})}}]}
        report=run_gold_deepseek_probe(GOLD_ROLES,gold_snapshot,Client)
        self.assertEqual(report["results"]["fire"]["decision"]["direction"],"WAIT")
        self.assertFalse(report["trade_authorized"])

    def test_catalogue_must_confirm_deepseek_before_any_completion(self):
        class Client:
            last_request_id=None
            def _call(self,url,*,body=None,timeout):
                if body is not None:self.fail("paid completion despite missing model")
                return {"data":[{"id":"tb-gpt-6"}]}
        with self.assertRaises(PlanError):
            run_gold_deepseek_probe(GOLD_ROLES,gold_snapshot,Client)


if __name__ == "__main__":
    unittest.main()
