"""Offline BTC cross-venue spot triage tests; no real HTTP or broker access."""
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.independent_spot_triage import (
    IndependentSpotError, inspect_external_spot_context,
    read_coinbase_spot, main,
)

FIRST = int(datetime(2026, 11, 4, 13, 15, tzinfo=timezone.utc).timestamp())


class FakeDelta:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, *, anomalous=True):
        self.requests = []
        self.anomalous = anomalous

    def _request(self, method, path, *, auth, params):
        assert method == "GET" and not auth
        assert path == "/v2/history/candles"
        self.requests.append((method, path, dict(params)))
        stamp = params["start"]
        if params["symbol"].startswith("MARK:"):
            return {"result": [{
                "time": stamp, "open": "60020", "high": "60050",
                "low": "59980", "close": "60010", "volume": None,
            }]}
        if params["resolution"] == "1m":
            return {"result": [
                {"time": stamp + 60 * i,
                 "open": "60000" if i == 0 else "60010",
                 "high": "80000" if self.anomalous and i == 0
                         else "60100",
                 "low": "0.1" if self.anomalous and i == 1
                        else "59900",
                 "close": "60010", "volume": "2"}
                for i in range(5)
            ]}
        return {"result": [{
            "time": stamp, "open": "60000",
            "high": "80000" if self.anomalous else "60100",
            "low": "0.1" if self.anomalous else "59900",
            "close": "60010", "volume": "10",
        }]}


def spot_close():
    return {
        "low": Decimal("59900"), "high": Decimal("60100"),
        "open": Decimal("60000"), "close": Decimal("60010"),
        "volume": Decimal("100"),
        "response_sha256": "f" * 64,
    }


class IndependentSpotTriageTests(unittest.TestCase):
    def test_suspicious_delta_extreme_is_detected_not_repaired(self):
        demo = FakeDelta(anomalous=True)
        result = inspect_external_spot_context(
            demo, [FIRST], spot_reader=lambda _: spot_close())
        self.assertIn("extreme_cross_venue_dislocation", result["blockers"])
        self.assertEqual(result["status"], "cross_venue_review_blocked")
        row = result["results"][0]
        self.assertEqual(row["cross_venue_observation"],
                         "extreme_cross_venue_dislocation_review_required")
        self.assertEqual(row["coinbase_spot_low"], "59900")
        self.assertEqual(row["delta_perpetual_low_to_coinbase_spot_low"],
                         str(Decimal("0.1")/Decimal("59900")))
        self.assertEqual(len(demo.requests), 3)
        self.assertFalse(result["independent_price_validation"])
        self.assertFalse(result["perpetual_trade_print_verified"])
        self.assertFalse(result["quarantine_release_authorized"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["archive_mutations"])
        self.assertFalse(result["broker_order_mutations"])

    def test_matching_spot_is_context_only_not_authorization(self):
        result = inspect_external_spot_context(
            FakeDelta(anomalous=False), [FIRST],
            spot_reader=lambda _: spot_close())
        self.assertEqual(
            result["status"],
            "cross_venue_spot_context_complete_manual_review_required")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["results"][0]["cross_venue_observation"],
                         "spot_context_only_perpetual_trade_unverified")
        self.assertFalse(result["results"][0][
            "spot_is_same_instrument_as_delta_perpetual"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["trade_authorized"])

    def test_external_spot_unavailable_is_fail_closed(self):
        def unavailable(stamp):
            raise IndependentSpotError("external_spot_unavailable")
        result = inspect_external_spot_context(
            FakeDelta(), [FIRST], spot_reader=unavailable)
        self.assertEqual(result["status"], "cross_venue_review_blocked")
        self.assertIn("external_spot_context_unavailable", result["blockers"])
        self.assertEqual(result["results"][0]["coinbase_spot_check"],
                         "external_spot_unavailable")

    def test_remote_exception_reason_not_disclosed(self):
        def explode(_):
            raise RuntimeError("RAW_CREDENTIAL=DO_NOT_PRINT")
        r = inspect_external_spot_context(
            FakeDelta(), [FIRST], spot_reader=explode)
        self.assertNotIn("RAW_CREDENTIAL=DO_NOT_PRINT", json.dumps(r))
        self.assertFalse(r["trade_authorized"])

    def test_invalid_client_blocks_all_network_calls(self):
        demo = FakeDelta()
        demo.allow_orders = True
        called = []
        result = inspect_external_spot_context(
            demo, [FIRST], spot_reader=lambda t: called.append(t))
        self.assertEqual(result["blockers"], ["read_only_demo_client_required"])
        self.assertEqual(called, [])
        self.assertEqual(demo.requests, [])

    def test_invalid_window_blocks_all_network_calls(self):
        demo = FakeDelta()
        called = []
        result = inspect_external_spot_context(
            demo, [FIRST+60], spot_reader=lambda t: called.append(t))
        self.assertEqual(result["blockers"], ["invalid_candle_window"])
        self.assertEqual(called, [])
        self.assertEqual(demo.requests, [])

    def test_public_coinbase_request_exact_aligned_bar_and_no_credentials(self):
        data = [[FIRST, 59900, 60100, 60000, 60010, 123]]
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return json.dumps(data).encode()
        class Opener:
            def open(self, req, timeout):
                self.req, self.timeout = req, timeout
                return Response()
        opener = Opener()
        with patch("tradebot.independent_spot_triage.request.build_opener",
                   return_value=opener):
            result = read_coinbase_spot(FIRST)
        self.assertEqual(opener.timeout, 8)
        self.assertEqual(opener.req.get_method(), "GET")
        self.assertTrue(opener.req.full_url.startswith(
            "https://api.exchange.coinbase.com/products/BTC-USD/candles?"))
        self.assertIn("granularity=300", opener.req.full_url)
        self.assertEqual(result["low"], Decimal("59900"))
        self.assertEqual(len(result["response_sha256"]), 64)
        self.assertNotIn("Authorization", opener.req.headers)

    def test_coinbase_malformed_stale_duplicate_and_suspicious_bars_rejected(self):
        examples = [
            ([[FIRST-300, 60000, 60100, 60010, 60020, 1]],
             "external_spot_target_missing_or_duplicated"),
            ([[FIRST, 60000, 60100, 60010, 60020, 1],
              [FIRST, 60000, 60100, 60010, 60020, 1]],
             "external_spot_target_missing_or_duplicated"),
            ([[FIRST, "NaN", 60100, 60010, 60020, 1]],
             "external_spot_numeric_invalid"),
            ([[FIRST, 60000, 59000, 60010, 60020, 1]],
             "external_spot_ohlcv_invalid"),
            ([[FIRST+60, 60000, 60100, 60010, 60020, 1]],
             "external_spot_timestamp_invalid"),
            ({"result": []}, "external_spot_response_invalid"),
        ]
        for data, code in examples:
            with self.subTest(code=code):
                class Response:
                    status = 200
                    def __enter__(self): return self
                    def __exit__(self, *unused): return False
                    def read(self, n): return json.dumps(data).encode()
                class Opener:
                    def open(self, req, timeout): return Response()
                with patch(
                        "tradebot.independent_spot_triage.request.build_opener",
                        return_value=Opener()):
                    with self.assertRaisesRegex(IndependentSpotError, code):
                        read_coinbase_spot(FIRST)

    def test_redirect_and_remote_errors_fail_closed_without_leaking(self):
        from urllib.error import URLError
        class Opener:
            def open(self, req, timeout):
                raise URLError("SECRET_DONT_LOG")
        with patch("tradebot.independent_spot_triage.request.build_opener",
                   return_value=Opener()):
            with self.assertRaisesRegex(IndependentSpotError,
                                        "external_spot_unavailable") as ctx:
                read_coinbase_spot(FIRST)
        self.assertNotIn("SECRET_DONT_LOG", str(ctx.exception))

    def test_command_uses_read_only_delta_demo_with_no_mutations(self):
        fake = FakeDelta(anomalous=False)
        with patch("tradebot.independent_spot_triage.DeltaDemo",
                   return_value=fake) as init:
            with patch("tradebot.independent_spot_triage.read_coinbase_spot",
                       return_value=spot_close()):
                with patch("builtins.print"):
                    code = main(["--at", "2026-11-04T13:15:00+00:00"])
        self.assertEqual(code, 0)
        init.assert_called_once_with(allow_orders=False)
        self.assertEqual(len(fake.requests), 3)


if __name__ == "__main__":
    unittest.main()
