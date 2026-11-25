import tempfile
import unittest
from pathlib import Path
from recover_trading.scanner import scan_once
from tradebot.market_data_v3 import FRAMES
from tradebot.delta import DEMO_API

NOW = 1800000000


class FixtureClient:
    base_url = DEMO_API
    allow_orders = False

    def candles(self, *, symbol, resolution, start, end):
        step = FRAMES[resolution]
        return [{"time": t, "open": 100 + i*.01, "high": 101 + i*.01,
                 "low": 99 + i*.01, "close": 100.2 + i*.01, "volume": 10 + i%5}
                for i,t in enumerate(range(start, end, step))]

    def ticker(self, symbol):
        raise RuntimeError("fixture quote unavailable")

    def _request(self, method, path, **kwargs):
        assert method == "GET"
        raise RuntimeError("fixture auxiliary feed unavailable")


def missing_reference():
    raise RuntimeError("fixture reference unavailable")


class ScannerTests(unittest.TestCase):
    def test_both_catalogs_and_partial_feed_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = scan_once(Path(tmp)/"market.sqlite", client=FixtureClient(),
                               clock=lambda: NOW, gold_reference=missing_reference, external_context=lambda: {})
        for symbol, implemented, deferred in (("BTCUSD", 48, 2), ("XAUTUSD", 47, 3)):
            row = report["markets"][symbol]
            self.assertIn("coverage", row, row)
            c = row["coverage"]
            self.assertEqual(c["implemented_rules"], implemented)
            self.assertEqual(c["deferred_rules"], deferred)
            self.assertGreater(c["evaluable_rules"], 0)
            self.assertGreater(c["unavailable_rules"], 0)
            self.assertEqual(c["evaluable_rules"] + c["unavailable_rules"], implemented)
            self.assertEqual(row["feed_health"]["ticker"]["status"], "unavailable")
        self.assertEqual(report["orders_submitted"], 0)
        self.assertEqual(report["ai_calls"], 0)
