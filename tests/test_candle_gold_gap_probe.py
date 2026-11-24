"""Offline no-order/no-write tests of bounded missing Gold source checks."""
from datetime import datetime, timezone
import unittest

from tradebot.candle_gold_gap_probe import gold_gap_probe

NOW = datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc)
START = int(datetime(2026, 10, 29, 22, 10, tzinfo=timezone.utc).timestamp())


def inventory(times, count=None, truncated=False):
    return {
        "status": "local_archive_issues_identified",
        "periods": {"XAUTUSD_previous_month": {
            "missing_bar_count": len(times) if count is None else count,
            "missing_utc_examples": [
                datetime.fromtimestamp(t, timezone.utc).isoformat() for t in times],
            "examples_truncated": {"missing": truncated},
        }},
    }


class DemoPublic:
    base_url = "https://cdn-ind.testnet.deltaex.org"
    allow_orders = False

    def __init__(self, missing=None, invalid=None):
        self.calls = []
        self.missing = set(missing or ())
        self.invalid = set(invalid or ())

    def _request(self, method, path, *, auth=False, params=None, **kwargs):
        assert method == "GET" and path == "/v2/history/candles"
        assert auth is False and params["symbol"] == "XAUTUSD"
        resolution = params["resolution"]
        assert resolution in ("1m", "5m")
        first = params["start"]
        self.calls.append((resolution, first))
        if (resolution, first) in self.missing:
            return {"result": []}
        count, step = (1, 300) if resolution == "5m" else (5, 60)
        out = []
        for j in range(count):
            out.append({
                "time": first+j*step,
                "open": "100", "high": "101", "low": "99",
                "close": "100", "volume": str(5 if resolution == "5m" else 1),
            })
        if (resolution, first) in self.invalid:
            out[0]["low"] = "0"
        return {"result": out}


def run(exchange, times, count=None, truncated=False):
    return gold_gap_probe(
        exchange, "/path/not/accessed/by_test", now=NOW,
        inventory_fn=lambda path, now: inventory(
            times, count=count, truncated=truncated))


class GoldGapSourceTests(unittest.TestCase):
    def test_three_genuine_gaps_check_only_exact_public_5m_and_1m(self):
        gaps = [START, START+300, START+600]
        fake = DemoPublic()
        result = run(fake, gaps)
        self.assertEqual(result["checked_bars"], 3)
        self.assertEqual(result["missing_gold_bars"], 3)
        self.assertEqual(result["status"], "same_provider_candles_available_for_review")
        self.assertEqual(fake.calls, [
            ("5m", stamp) if j == 0 else ("1m", stamp)
            for stamp in gaps for j in range(2)])
        self.assertTrue(all(x["same_provider_1m_5m_agreement"]
                            for x in result["candidate_results"]))
        for flag in ("trade_authorized", "safe_to_enable_fire",
                     "archive_mutations", "financial_ledger_mutations",
                     "broker_order_mutations", "credentialed_broker_calls",
                     "broker_archive_recovery_confirmed", "independent_price_validation"):
            self.assertFalse(result[flag])

    def test_missing_five_minute_source_never_invents_bar(self):
        fake = DemoPublic(missing={("5m", START)})
        result = run(fake, [START])
        self.assertEqual(result["status"], "provider_gap_or_disagreement")
        self.assertEqual(result["candidate_results"][0]["trade_5m"],
                         "unavailable_or_invalid")
        self.assertFalse(result["safe_to_enable_fire"])

    def test_invalid_one_minute_source_cannot_validate_broker_candle(self):
        fake = DemoPublic(invalid={("1m", START)})
        result = run(fake, [START])
        self.assertEqual(result["status"], "provider_gap_or_disagreement")
        self.assertFalse(result["candidate_results"][0]["same_provider_1m_5m_agreement"])

    def test_empty_inventory_does_not_contact_broker(self):
        fake = DemoPublic()
        result = run(fake, [])
        self.assertEqual(result["status"], "no_missing_gold_bars_locally")
        self.assertEqual(fake.calls, [])
        self.assertFalse(result["trade_authorized"])

    def test_truncated_gap_inventory_blocks_before_network(self):
        fake = DemoPublic()
        result = run(fake, [START] * 9, truncated=True)
        self.assertEqual(result["reason"], "missing_window_not_bounded")
        self.assertEqual(fake.calls, [])

    def test_untrusted_out_of_month_and_duplicate_timestamps_block(self):
        for gaps in ([START, START], [int(NOW.timestamp())],
                     [START+30]):
            with self.subTest(gaps=gaps):
                fake = DemoPublic()
                result = run(fake, gaps)
                self.assertEqual(result["reason"], "original_gap_inventory_unverified")
                self.assertEqual(fake.calls, [])

    def test_wrong_broker_or_order_enabled_aborts_before_network(self):
        for base, allowed in (("https://api.delta.exchange", False),
                              (DemoPublic.base_url, True)):
            fake = DemoPublic()
            fake.base_url, fake.allow_orders = base, allowed
            result = run(fake, [START])
            self.assertEqual(result["reason"], "public_read_only_demo_required")
            self.assertEqual(fake.calls, [])

    def test_full_audit_remains_separately_fail_closed(self):
        from pathlib import Path
        audit = (Path(__file__).resolve().parents[1] /
                 "ops/run_btc_demo_release_audit.sh").read_text()
        self.assertIn("TRADING_ENABLED: false", audit)
        self.assertTrue(audit.rstrip().endswith("exit 2"))


if __name__ == "__main__":
    unittest.main()
