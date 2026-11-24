"""Offline BTC pre-model quality rejection; no broker or AI integration."""
from copy import deepcopy
import unittest
from tradebot.btc_market_screen import screen_btc_market, MarketScreenRejected
from tradebot.fire_execution import FireDemoController

def fixture():
    return (
        {"core":{"ticker":{"symbol":"BTCUSD","mark_price":"60000"},
                 "best_bid":"59999","best_ask":"60001"}},
        {"atr_5m":"120",
         "ema_15m":{"ema20":"59940","close":"60000","slope":"rising"},
         "ema_1h":{"ema20":"59900","close":"59990","slope":"rising"},
         "session_vwap":"59900"}
    )

class BTCMarketScreenTests(unittest.TestCase):
    def test_valid_spread_and_atr_quality_is_non_authorizing(self):
        snapshot, context = fixture()
        r = screen_btc_market(snapshot,context)
        self.assertEqual(r["status"],"passed")
        self.assertFalse(r["trade_authorized"])
        self.assertFalse(r["independent_price_verified"])
    def test_normal_fire_hook_unmodified(self):
        snapshot, context = fixture()
        self.assertIsNone(FireDemoController._pre_model_market_screen(
            None,snapshot,context))
    def test_wide_spread_rejected(self):
        snapshot, context = fixture()
        snapshot["core"]["best_ask"]="60100"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_spread_too_wide"):
            screen_btc_market(snapshot,context)
    def test_spread_over_atr_share_rejected(self):
        snapshot, context = fixture()
        context["atr_5m"]="1"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_spread_vs_volatility"):
            screen_btc_market(snapshot,context)
    def test_mark_mismatch_rejected(self):
        snapshot, context = fixture()
        snapshot["core"]["ticker"]["mark_price"]="61100"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_mark_dislocation"):
            screen_btc_market(snapshot,context)
    def test_extreme_volatility_rejected(self):
        snapshot, context = fixture()
        context["atr_5m"]="4000"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_extreme_volatility"):
            screen_btc_market(snapshot,context)
    def test_missing_or_invalid_required_indicators_rejected(self):
        for value in (None, 0, "NaN", "Infinity", -1, True):
            with self.subTest(value=value):
                snapshot, context=fixture()
                context["atr_5m"]=value
                with self.assertRaises(MarketScreenRejected):
                    screen_btc_market(snapshot,context)
        snapshot, context=fixture()
        context["ema_15m"]["slope"]="secret-direction"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_trend_unavailable"):
            screen_btc_market(snapshot,context)
    def test_quote_and_product_mismatch_rejected(self):
        snapshot, context=fixture()
        snapshot["core"]["ticker"]["symbol"]="XAUTUSD"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_wrong_market"):
            screen_btc_market(snapshot,context)
        snapshot, context=fixture()
        snapshot["core"]["best_ask"]="59900"
        with self.assertRaisesRegex(MarketScreenRejected,"market_screen_crossed_quote"):
            screen_btc_market(snapshot,context)
    def test_vwap_optional_but_invalid_vwap_rejected(self):
        snapshot,context=fixture()
        context["session_vwap"]=None
        self.assertEqual(screen_btc_market(snapshot,context)["status"],"passed")
        context["session_vwap"]="NaN"
        with self.assertRaises(MarketScreenRejected):
            screen_btc_market(snapshot,context)
