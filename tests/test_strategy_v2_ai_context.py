"""Model-context contract for independent Strategy V2 events."""
from hashlib import sha256
from copy import deepcopy
import unittest
from tradebot.strategy_v2.ai_context import build_model_context
from tradebot.signal_ai_router import build_ai_signal_event
from test_multi_strategy_signals import candles
from test_signal_ai_router import scan, candidate
from tradebot.multi_strategy_signals import STRATEGIES


def example(symbol="BTCUSD",signals=None):
    rows=candles(250)
    t=rows[-1]["time"]
    if signals is None:
        signals=[candidate(symbol=symbol,stamp=t)]
    s=scan(symbol,signals=signals)
    s["candle_time"]=t
    sides={v["direction"] for v in signals}
    s["conflicting_directions"]=len(sides)>1
    s["direction_hint"]=next(iter(sides)) if len(sides)==1 else None
    return build_ai_signal_event(s),rows


class ModelContextTests(unittest.TestCase):
    def test_one_signal_btc_includes_indicators_no_order_permission(self):
        event,bars=example()
        context=build_model_context(event,bars)
        self.assertEqual(context["model_route"],"GPT-6")
        self.assertEqual(context["trigger_rule"],
                         "one_qualifying_detector_suffices")
        self.assertEqual(len(context["signals"]),1)
        self.assertIn("rsi14",context["indicators"])
        self.assertIn("ema200",context["indicators"])
        self.assertIn("session_vwap",context["indicators"])
        self.assertEqual(context["closed_candle_time"],bars[-1]["time"])
        self.assertFalse(context["constraints"]["trade_authorized"])
        self.assertTrue(context["constraints"]["risk_governor_required"])
        self.assertNotIn("wallet",repr(context))

    def test_gold_routes_deepseek(self):
        event,bars=example("XAUTUSD")
        self.assertEqual(build_model_context(event,bars)["model_route"],
                         "DeepSeek")

    def test_opposite_signals_pass_as_explicit_conflict(self):
        bars=candles(250)
        t=bars[-1]["time"]
        signals=[candidate(stamp=t),
                 candidate(stamp=t,strategy=STRATEGIES[8],direction="SHORT",score=85)]
        event,rows=example(signals=signals)
        context=build_model_context(event,rows)
        self.assertTrue(context["conflicting_directions"])
        self.assertEqual(len(context["signals"]),2)
        self.assertFalse(context["constraints"]["trade_authorized"])

    def test_forged_event_id_and_model_rejected(self):
        event,rows=example()
        for key,value in (("event_id","fake"),("model","unapproved"),
                          ("execution_authorized",True),("dispatch_ai",False)):
            altered=deepcopy(event);altered[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    build_model_context(altered,rows)

    def test_signal_identity_and_scores_checked(self):
        event,rows=example()
        for key,value in (("signal_id","wrong"),("score",58),
                          ("strength","strong"),("strategy_id","unknown")):
            altered=deepcopy(event);altered["signals"][0][key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    build_model_context(altered,rows)

    def test_candle_gap_and_mismatch_rejected(self):
        event,rows=example()
        with self.assertRaises(ValueError):
            build_model_context(event,rows[:-1])
        with self.assertRaises(ValueError):
            build_model_context(event,rows[:100]+rows[101:])

    def test_no_model_call_or_account_access(self):
        event,rows=example()
        context=build_model_context(event,rows)
        self.assertEqual(context["decision_required"],
                         "evaluate_opportunity_not_execute")
        self.assertNotIn("contracts",context)
        self.assertNotIn("leverage",context)

