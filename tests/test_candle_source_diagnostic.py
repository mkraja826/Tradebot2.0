"""Offline public candle source cross-check tests. Never accesses a broker."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from tradebot.candle_source_diagnostic import (
    _timestamp, compare_sources, main,
)
from tradebot.delta import DEMO_API


FIRST = int(datetime(2026, 11, 4, 13, 15, tzinfo=timezone.utc).timestamp())


class FakeReadOnlyDelta:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self):
        self.calls = []
        self.no_mark = False
        self.mismatch = False

    def _request(self, method, path, *, auth, params):
        assert method == "GET"
        assert path == "/v2/history/candles"
        assert auth is False
        self.calls.append((method, path, dict(params)))
        start = params["start"]
        symbol = params["symbol"]
        if symbol.startswith("MARK:"):
            if self.no_mark:
                raise RuntimeError("SECRET_API_KEY_DO_NOT_LOG")
            return {"result": [{
                "time": start, "open": "60300", "high": "60350",
                "low": "60250", "close": "60325", "volume": "0"}]}
        if params["resolution"] == "1m":
            return {"result": [{
                "time": start + i * 60,
                "open": "60300" if i == 0 else "60325",
                "high": "79999" if i == 0 else "60350",
                "low": "0.1" if i == 2 else "60250",
                "close": "60325",
                "volume": "1",
            } for i in range(5)]}
        return {"result": [{
            "time": start, "open": "60300",
            "high": "80000" if self.mismatch else "79999",
            "low": "0.1", "close": "60325", "volume": "5"}]}


class CandleSourceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.broker = FakeReadOnlyDelta()

    def test_public_get_only_crosschecks_without_trade_permission(self):
        r = compare_sources(self.broker, [FIRST])
        self.assertEqual(r["status"], "source_crosscheck_complete_review_still_required")
        self.assertFalse(r["trade_authorized"])
        self.assertFalse(r["safe_to_enable_fire"])
        self.assertFalse(r["archive_mutations"])
        self.assertFalse(r["broker_order_mutations"])
        self.assertFalse(r["independent_price_validation"])
        self.assertEqual(len(self.broker.calls), 3)
        self.assertTrue(r["results"][0]["five_minute_ohlc_matches_one_minute"])
        self.assertTrue(r["results"][0]["five_minute_volume_matches_one_minute"])
        self.assertEqual(r["results"][0]["mark_5m_low"], "60250")

    def test_crossresolution_mismatch_fails_closed(self):
        self.broker.mismatch = True
        r = compare_sources(self.broker, [FIRST])
        self.assertIn("cross_resolution_ohlc_mismatch", r["blockers"])
        self.assertEqual(r["status"], "review_required")
        self.assertFalse(r["results"][0]["five_minute_ohlc_matches_one_minute"])

    def test_missing_mark_is_sanitized_and_never_green(self):
        self.broker.no_mark = True
        r = compare_sources(self.broker, [FIRST])
        self.assertIn("candle_source_comparison_unverified", r["blockers"])
        self.assertNotIn("SECRET_API_KEY_DO_NOT_LOG", json.dumps(r))
        self.assertEqual(r["results"][0]["comparison"], "unverified")

    def test_malformed_list_and_duplicate_or_missing_minute_fails(self):
        original = self.broker._request

        def bad(method, path, *, auth, params):
            data = original(method, path, auth=auth, params=params)
            if params["resolution"] == "1m":
                data["result"].pop()
            return data

        self.broker._request = bad
        r = compare_sources(self.broker, [FIRST])
        self.assertEqual(r["status"], "review_required")
        self.assertIn("candle_source_comparison_unverified", r["blockers"])

    def test_order_enabled_or_wrong_broker_endpoint_rejected_before_reads(self):
        for field, value in (("allow_orders", True),
                             ("base_url", "https://live.invalid")):
            with self.subTest(field=field):
                original = getattr(self.broker, field)
                setattr(self.broker, field, value)
                r = compare_sources(self.broker, [FIRST])
                self.assertEqual(r["blockers"], ["read_only_demo_client_required"])
                self.assertEqual(self.broker.calls, [])
                setattr(self.broker, field, original)

    def test_bad_windows_block_without_network(self):
        for times in ([], [FIRST, FIRST], [FIRST+60], [0],
                      [FIRST] * 21, ["2026-11-04T13:15:00Z"]):
            with self.subTest(times=times):
                r = compare_sources(self.broker, times)
                self.assertEqual(r["blockers"], ["invalid_candle_window"])
        self.assertEqual(self.broker.calls, [])

    def test_iso_timestamp_validation(self):
        self.assertEqual(_timestamp("2026-11-04T13:15:00+00:00"), FIRST)
        from argparse import ArgumentTypeError
        for value in ("2026-11-04T13:16:00+00:00",
                      "2026-11-04T13:15:30+00:00",
                      "2026-11-04T13:15:00"):
            with self.assertRaises(ArgumentTypeError):
                _timestamp(value)

    def test_cli_invokes_public_read_only_client(self):
        with patch("tradebot.candle_source_diagnostic.DeltaDemo") as client:
            client.return_value = self.broker
            with patch("builtins.print"):
                self.assertEqual(main(["--at", "2026-11-04T13:15:00+00:00"]), 0)
            client.assert_called_once_with(allow_orders=False)
        self.assertEqual(len(self.broker.calls), 3)


if __name__ == "__main__":
    unittest.main()
