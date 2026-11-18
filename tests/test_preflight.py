import unittest
from datetime import datetime, timezone

from tradebot.ai import OrderIntent, TradePlan
from tradebot.preflight import PreflightError, check_entry

T = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
FUTURE = {"id": 1, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
          "state": "live"}
OPTION = {"id": 2, "symbol": "C-BTC-90000-271126",
          "contract_type": "call_options", "state": "live"}
ETH = {"id": 3, "symbol": "ETHUSD", "contract_type": "perpetual_futures",
       "state": "live"}


class Exchange:
    def __init__(self):
        self.age = 1
        self.bid = "100"
        self.ask = "101"
        self.eq = "1000"
        self.available = "100"
        self.quote_calls = 0

    def ticker(self, symbol):
        self.quote_calls += 1
        return {"symbol": symbol, "timestamp": int(T.timestamp()) - self.age,
                "quotes": {"best_bid": self.bid, "best_ask": self.ask}}

    def wallet_balances(self):
        return {"balances": [{"asset_symbol": "USD",
                              "available_balance": self.available}],
                "meta": {"net_equity": self.eq}}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.ex = Exchange()
        self.plan = TradePlan("AI spread", "research",
                              (OrderIntent(1, "buy", 1),
                               OrderIntent(2, "sell", 2)))

    def check(self, plan=None, now=T):
        return check_entry(self.ex, plan or self.plan,
                           [FUTURE, OPTION, ETH], now=now)

    def test_fresh_balanced_two_leg_plan(self):
        result = self.check()
        self.assertEqual(result.quoted_legs, 2)
        self.assertEqual(result.spendable_demo_assets, ("USD",))
        self.assertFalse(result.broker_margin_verified)

    def test_stale_quote_refuses_order(self):
        self.ex.age = 70
        with self.assertRaises(PreflightError):
            self.check()

    def test_crossed_quote_refuses_order(self):
        self.ex.bid = "200"
        with self.assertRaises(PreflightError):
            self.check()

    def test_insufficient_demo_funds(self):
        self.ex.available = "0"
        with self.assertRaises(PreflightError):
            self.check()

    def test_no_equity(self):
        self.ex.eq = "0"
        with self.assertRaises(PreflightError):
            self.check()

    def test_non_btc_product_is_rejected(self):
        bad = TradePlan("incorrect", "test", (OrderIntent(3, "buy", 1),))
        with self.assertRaises(PreflightError):
            self.check(bad)
        self.assertEqual(self.ex.quote_calls, 0)

    def test_after_session_is_rejected_without_network(self):
        with self.assertRaises(PreflightError):
            self.check(now=datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc))
        self.assertEqual(self.ex.quote_calls, 0)

    def test_wait_is_valid_without_wallet(self):
        result = self.check(TradePlan("WAIT", "no edge", ()))
        self.assertEqual(result.quoted_legs, 0)
        self.assertEqual(self.ex.quote_calls, 0)

    def test_fractional_contracts_blocked(self):
        bad = TradePlan("wrong", "qty", (OrderIntent(1, "buy", 0.2),))
        with self.assertRaises(PreflightError):
            self.check(bad)


if __name__ == "__main__":
    unittest.main()
