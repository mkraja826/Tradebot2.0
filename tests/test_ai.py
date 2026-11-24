import unittest

from tradebot.ai import PlanError, validate_plan

PRODUCTS = [
    {"id": 1, "symbol": "BTCUSD", "contract_type": "perpetual_futures", "state": "live"},
    {"id": 2, "symbol": "C-BTC-90000-201126", "contract_type": "call_options", "state": "live"},
    {"id": 3, "symbol": "ETHUSD", "contract_type": "perpetual_futures", "state": "live"},
]


class TestPlanning(unittest.TestCase):
    def test_wait_allowed(self):
        plan = validate_plan({"strategy": "wait", "rationale": "No edge", "orders": []}, PRODUCTS)
        self.assertEqual(plan.orders, ())

    def test_unconstrained_strategy_names(self):
        plan = validate_plan({
            "strategy": "AI-developed volatility hedge",
            "rationale": "Demo opportunity",
            "orders": [{"product_id": 1, "side": "buy", "size": 2},
                       {"product_id": 2, "side": "sell", "size": 1}],
        }, PRODUCTS)
        self.assertEqual(len(plan.orders), 2)

    def test_eth_blocked(self):
        with self.assertRaises(PlanError):
            validate_plan({"strategy": "wrong", "rationale": "not BTC",
                           "orders": [{"product_id": 3, "side": "buy", "size": 1}]}, PRODUCTS)

    def test_rejects_fractional_contract_size(self):
        with self.assertRaises(PlanError):
            validate_plan({"strategy": "wrong", "rationale": "wrong size",
                           "orders": [{"product_id": 1, "side": "buy", "size": 0.1}]}, PRODUCTS)
