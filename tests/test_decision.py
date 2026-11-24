import unittest

from tradebot.decision import build_ai_context


def base_snapshot():
    option_quotes = []
    for expiry in ("2026-11-20T12:00:00Z", "2026-11-27T12:00:00Z"):
        for kind, prefix in (("call_options", "C"), ("put_options", "P")):
            for offset in (-200, -100, 0, 100, 200):
                option_quotes.append({
                    "product_id": len(option_quotes) + 100,
                    "symbol": f"{prefix}-BTC-{10000+offset}-201126",
                    "contract_type": kind, "state": "live",
                    "usable_quote": True,
                    "strike_price": str(10000 + offset),
                    "settlement_time": expiry,
                    "bid": "90", "ask": "100", "greeks": {"delta": "0.5"},
                    "contract_value": "0.001",
                })
    return {
        "environment": "delta-india-demo",
        "session_phase": "trading",
        "collected_at": "2026-11-18T00:00:00+00:00",
        "core": {"best_bid": "9999", "best_ask": "10001",
                 "ticker": {"spot_price": "10000"}},
        "technical": {"return_1h_pct": 0.8},
        "futures": [{"product_id": 1, "symbol": "BTCUSD",
                     "contract_type": "perpetual_futures",
                     "usable_quote": True}],
        "options": option_quotes,
        "demo_funds": {"net_equity": "10000",
                       "wallets": [{"asset": "USD", "available_balance": "9000"}]},
    }


class ContextTests(unittest.TestCase):
    def test_balances_calls_puts_expiries(self):
        ctx, products = build_ai_context(base_snapshot(), max_options=8)
        self.assertEqual(len(ctx["options"]), 8)
        self.assertEqual(len(products), 9)
        distinct = {(x["contract_type"], x["settlement_time"])
                    for x in ctx["options"]}
        self.assertEqual(len(distinct), 4)
        self.assertTrue(all(x["state"] == "live" for x in products))
        self.assertEqual(ctx["coverage"]["usable_option_quotes_total"], 20)
        self.assertEqual(ctx["coverage"]["sampled_option_quotes"], 8)
        self.assertEqual(ctx["demo_funds"]["wallets"][0]["asset"], "USD")

    def test_near_money_selected_before_far_wings(self):
        ctx, _ = build_ai_context(base_snapshot(), max_options=8)
        self.assertTrue(all(abs(int(x["strike_price"]) - 10000) <= 100
                            for x in ctx["options"]))

    def test_bad_quotes_never_become_execution_candidates(self):
        snapshot = base_snapshot()
        snapshot["options"][0]["usable_quote"] = False
        _, products = build_ai_context(snapshot, max_options=32)
        self.assertNotIn(snapshot["options"][0]["product_id"],
                         {p["id"] for p in products})

    def test_future_only_is_supported(self):
        snap = base_snapshot()
        snap["options"] = []
        ctx, products = build_ai_context(snap)
        self.assertEqual(len(ctx["options"]), 0)
        self.assertEqual(len(products), 1)

    def test_no_valid_contract_rejected(self):
        snap = base_snapshot()
        snap["options"] = []
        snap["futures"] = []
        with self.assertRaises(ValueError):
            build_ai_context(snap)

    def test_budget_is_explicit(self):
        with self.assertRaises(ValueError):
            build_ai_context(base_snapshot(), max_options=1)
        with self.assertRaises(ValueError):
            build_ai_context(base_snapshot(), max_options=900)


if __name__ == "__main__":
    unittest.main()
