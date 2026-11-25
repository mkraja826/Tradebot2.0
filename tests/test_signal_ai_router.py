"""Offline signal-to-AI routing contract, idempotency and fail-closed tests."""
import copy
from hashlib import sha256
import unittest

from tradebot.signal_ai_router import build_ai_signal_event
from tradebot.multi_strategy_signals import STRATEGIES


def candidate(symbol="BTCUSD",stamp=1800000000,strategy=STRATEGIES[0],
              direction="LONG",score=70):
    identity=f"{symbol}:{stamp}:{strategy}:{direction}"
    return {"strategy_id":strategy,"direction":direction,"score":score,
            "strength":"strong" if score>=80 else "moderate",
            "signal_id":sha256(identity.encode()).hexdigest()[:20],
            "candle_time":stamp,"trade_authorized":False}


def scan(symbol="BTCUSD",signals=None):
    s=[candidate(symbol)] if signals is None else signals
    sides={x["direction"] for x in s}
    return {"symbol":symbol,"candle_time":1800000000,"trigger_ai":bool(s),
            "signals":s,"candidate_count":len(s),
            "conflicting_directions":len(sides)>1,
            "direction_hint":next(iter(sides)) if len(sides)==1 else None,
            "execution_authorized":False,
            "source":"completed_5m_local_1_of_10"}


class SignalAIEventTests(unittest.TestCase):
    def test_single_strategy_dispatches_correct_ai(self):
        result=build_ai_signal_event(scan())
        self.assertTrue(result["dispatch_ai"])
        self.assertEqual(result["model"],"GPT-6")
        self.assertEqual(result["signal_rule"],"one_of_ten")
        self.assertEqual(len(result["signals"]),1)
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["requires_fresh_broker_and_risk_checks"])

    def test_gold_routes_deepseek(self):
        result=build_ai_signal_event(scan("XAUTUSD"))
        self.assertEqual(result["model"],"DeepSeek")
        self.assertTrue(result["dispatch_ai"])

    def test_exactly_one_event_per_candle(self):
        s=scan()
        first=build_ai_signal_event(s)
        second=build_ai_signal_event(s,processed={first["event_id"]})
        self.assertFalse(second["dispatch_ai"])
        self.assertEqual(second["status"],"duplicate_candle_event")

    def test_multiple_same_direction_signals_share_one_event(self):
        entries=[candidate(strategy=STRATEGIES[0]),
                 candidate(strategy=STRATEGIES[2])]
        result=build_ai_signal_event(scan(signals=entries))
        self.assertTrue(result["dispatch_ai"])
        self.assertEqual(len(result["signals"]),2)

    def test_opposing_signals_are_one_ai_conflict_evaluation(self):
        entries=[candidate(strategy=STRATEGIES[0]),
                 candidate(strategy=STRATEGIES[9],direction="SHORT",score=85)]
        result=build_ai_signal_event(scan(signals=entries))
        self.assertEqual(result["model"],"GPT-6")
        self.assertTrue(result["conflicting_directions"])
        self.assertTrue(result["dispatch_ai"])
        self.assertFalse(result["execution_authorized"])

    def test_no_signal_means_no_api_call(self):
        result=build_ai_signal_event(scan(signals=[]))
        self.assertFalse(result["dispatch_ai"])
        self.assertEqual(result["status"],"no_qualifying_signal")

    def test_forged_or_duplicated_signal_rejected(self):
        base=scan()
        invalid=copy.deepcopy(base)
        invalid["signals"][0]["signal_id"]="forged"
        for test in (invalid, scan(signals=[base["signals"][0]]*2)):
            with self.assertRaises(ValueError):
                build_ai_signal_event(test)

    def test_bypass_flags_never_enable_trading(self):
        for key,value in (("execution_authorized",True),
                          ("source","untrusted"),
                          ("trigger_ai",False),
                          ("candidate_count",9)):
            event=scan()
            event[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    build_ai_signal_event(event)

    def test_mismatched_strength_and_price_bar_rejected(self):
        for change in ({"strength":"strong"},{"candle_time":1800000300},
                       {"score":99},{"trade_authorized":True}):
            event=scan()
            event["signals"][0].update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    build_ai_signal_event(event)

    def test_conflict_flag_cannot_be_forged(self):
        event=scan()
        event["conflicting_directions"]=True
        with self.assertRaises(ValueError):
            build_ai_signal_event(event)

