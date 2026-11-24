"""Offline tests for the read-only BTC and Gold shadow monitor."""
import unittest
from unittest.mock import patch
from tradebot.delta import DEMO_API
from tradebot.signal_shadow_scan import sample_market, run_shadow
from test_multi_strategy_signals import candles
from test_signal_ai_router import scan


class FakeBroker:
    base_url=DEMO_API
    allow_orders=False
    def __init__(self, fail_symbol=None):
        self.calls=[]
        self.fail_symbol=fail_symbol
    def candles(self, *, symbol, resolution, start, end):
        self.calls.append((symbol,resolution,start,end))
        if self.fail_symbol==symbol:
            raise RuntimeError("public feed failed")
        return candles(250)


class ShadowScannerTests(unittest.TestCase):
    def test_both_market_scans_are_read_only(self):
        broker=FakeBroker()
        bars=candles(250)
        result=run_shadow(broker=broker,now=bars[-1]["time"]+300)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["ai_requests"],0)
        self.assertEqual(result["broker_mutations"],0)
        self.assertEqual([i["symbol"] for i in result["markets"]],
                         ["BTCUSD","XAUTUSD"])
        self.assertEqual(len(broker.calls),2)
        self.assertTrue(all(i["mode"]=="SHADOW_NO_AI_NO_ORDERS"
                            and not i["execution_authorized"]
                            for i in result["markets"]))

    def test_one_market_feed_failure_does_not_stop_other_market(self):
        broker=FakeBroker(fail_symbol="BTCUSD")
        bars=candles(250)
        result=run_shadow(broker=broker,now=bars[-1]["time"]+300)
        self.assertEqual(result["markets"][0]["status"],"signal_scan_unavailable")
        self.assertEqual(result["markets"][1]["mode"],"SHADOW_NO_AI_NO_ORDERS")
        self.assertEqual(len(broker.calls),2)

    def test_mutable_broker_rejected(self):
        broker=FakeBroker();broker.allow_orders=True
        bars=candles(250)
        with self.assertRaises(ValueError):
            sample_market(broker,"BTCUSD",as_of=bars[-1]["time"]+300)
        self.assertEqual(broker.calls,[])

    def test_true_qualifying_signal_only_logs_intent(self):
        broker=FakeBroker()
        bars=candles(250)
        event=scan("BTCUSD")
        event["candle_time"]=bars[-1]["time"]
        event["signals"][0]["candle_time"]=bars[-1]["time"]
        from hashlib import sha256
        s=event["signals"][0]
        s["signal_id"]=sha256(f'BTCUSD:{bars[-1]["time"]}:{s["strategy_id"]}:LONG'.encode()).hexdigest()[:20]
        with patch("tradebot.signal_shadow_scan.scan_completed_5m",return_value=event):
            result=sample_market(broker,"BTCUSD",as_of=bars[-1]["time"]+300)
        self.assertTrue(result["trigger_ai_if_connected"])
        self.assertEqual(result["ai_route"],"GPT-6")
        self.assertFalse(result["execution_authorized"])

    def test_broker_environment_mismatch_fails_closed(self):
        broker=FakeBroker();broker.base_url="https://some-other-host.example"
        with self.assertRaises(ValueError):
            sample_market(broker,"XAUTUSD",as_of=candles(250)[-1]["time"]+300)

