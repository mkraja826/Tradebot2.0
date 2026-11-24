"""No-network tests for public BTC spot cross-check."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from tradebot.btc_public_reference import (
    PublicReferenceRejected, corroborate_delta_quote, read_coinbase_spot)

NOW=datetime(2026,11,22,20,45,tzinfo=timezone.utc)
def delta(mark="60000"):
    return {"core":{"ticker":{"symbol":"BTCUSD","mark_price":mark}}}
def spot(bid="59999",ask="60001",at=None):
    return {"source":"coinbase_exchange_btc_usd_spot","bid":bid,"ask":ask,
            "observed_at":(at or NOW).isoformat()}

class PublicReferenceTests(unittest.TestCase):
    def test_fresh_spot_corroborates_but_never_authorizes(self):
        result=corroborate_delta_quote(delta(),spot(),now=NOW)
        self.assertEqual(result["status"],"spot_reference_corroborated")
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["independent_perpetual_trade_print_verified"])
    def test_stale_future_and_dislocated_prices_fail(self):
        for instant in (NOW-timedelta(seconds=31),NOW+timedelta(seconds=6)):
            with self.assertRaisesRegex(PublicReferenceRejected,"public_reference_stale"):
                corroborate_delta_quote(delta(),spot(at=instant),now=NOW)
        with self.assertRaisesRegex(PublicReferenceRejected,"public_reference_dislocated"):
            corroborate_delta_quote(delta("62000"),spot(),now=NOW)
    def test_crossed_or_wide_spot_spread_fails(self):
        with self.assertRaisesRegex(PublicReferenceRejected,"public_reference_crossed_quote"):
            corroborate_delta_quote(delta(),spot(60010,60000),now=NOW)
        with self.assertRaisesRegex(PublicReferenceRejected,"public_reference_spread_wide"):
            corroborate_delta_quote(delta(),spot(59000,60000),now=NOW)
    def test_untrusted_inputs_fail(self):
        for value in (None,{},spot(bid="NaN"),spot(ask="Infinity")):
            with self.assertRaises(PublicReferenceRejected):
                corroborate_delta_quote(delta(),value,now=NOW)
        other=delta();other["core"]["ticker"]["symbol"]="XAUTUSD"
        with self.assertRaisesRegex(PublicReferenceRejected,"public_reference_wrong_market"):
            corroborate_delta_quote(other,spot(),now=NOW)
    def test_public_get_is_keyless_bounded(self):
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,size):
                assert size==4097
                return json.dumps({"bid":"59999","ask":"60001",
                                   "time":NOW.isoformat()}).encode()
        class Opener:
            def open(self,req,timeout):
                self.method=req.get_method()
                self.url=req.full_url
                self.timeout=timeout
                return Response()
        opener=Opener()
        with patch("tradebot.btc_public_reference.request.build_opener",
                   return_value=opener):
            result=read_coinbase_spot()
        self.assertEqual(opener.method,"GET")
        self.assertEqual(opener.timeout,5)
        self.assertIn("/products/BTC-USD/ticker",opener.url)
        self.assertEqual(result["source"],"coinbase_exchange_btc_usd_spot")
    def test_public_get_failure_redacts_error(self):
        class Opener:
            def open(self,*args,**kwargs):
                raise OSError("sensitive upstream error")
        with patch("tradebot.btc_public_reference.request.build_opener",
                   return_value=Opener()):
            with self.assertRaises(PublicReferenceRejected) as ctx:
                read_coinbase_spot()
        self.assertEqual(str(ctx.exception),"public_reference_unavailable")
