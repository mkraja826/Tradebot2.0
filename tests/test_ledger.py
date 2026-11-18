import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tradebot.ledger import (
    LedgerError, fill_summary, ingest_fills, record_equity
)


def a_fill(**overrides):
    result = {
        "id": "fill-1", "created_at": "1795000000000000",
        "product_symbol": "BTCUSD", "side": "buy", "size": "2",
        "price": "91000", "notional": "182",
        "commission": "0.55", "settling_asset_symbol": "USD",
        "order_id": "order-1",
    }
    result.update(overrides)
    return result


class LedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name) / "fills.sqlite")

    def test_empty_ledger(self):
        self.assertEqual(fill_summary(self.path)["confirmed_btc_fills"], 0)

    def test_idempotent_retried_page_doesnt_double_count(self):
        batch = [a_fill(), a_fill(id="fill-2", side="sell",
                                  product_symbol="P-BTC-95000-271126",
                                  commission="0.15")]
        self.assertEqual(ingest_fills(self.path, batch)["new_fills"], 2)
        repeat = ingest_fills(self.path, batch)
        self.assertEqual(repeat["new_fills"], 0)
        self.assertEqual(repeat["duplicate_fills"], 2)
        summary = fill_summary(self.path)
        self.assertEqual(summary["confirmed_btc_fills"], 2)
        self.assertEqual(summary["fees_by_asset"], {"USD": "0.70"})
        self.assertFalse(summary["is_realized_pnl"])

    def test_different_assets_not_summed_together(self):
        ingest_fills(self.path, [
            a_fill(),
            a_fill(id="fill-2", settling_asset_symbol="INR",
                   commission="2.50", side="sell"),
        ])
        self.assertEqual(fill_summary(self.path)["fees_by_asset"],
                         {"INR": "2.50", "USD": "0.55"})

    def test_btc_only_reject_eth(self):
        with self.assertRaises(LedgerError):
            ingest_fills(self.path, [a_fill(product_symbol="ETHUSD")])

    def test_reject_nan_and_no_fill_id(self):
        with self.assertRaises(LedgerError):
            ingest_fills(self.path, [a_fill(commission="nan")])
        with self.assertRaises(LedgerError):
            ingest_fills(self.path, [a_fill(id=None)])

    def test_atomic_failed_batch_doesnt_write_partial(self):
        with self.assertRaises(LedgerError):
            ingest_fills(self.path, [a_fill(), a_fill(
                id="bad", settling_asset_symbol=None)])
        self.assertEqual(fill_summary(self.path)["confirmed_btc_fills"], 0)

    def test_date_filter(self):
        ingest_fills(self.path, [
            a_fill(),
            a_fill(id="fill-2", created_at="1797000000000000"),
        ])
        self.assertEqual(fill_summary(self.path, since_us=1796000000000000)
                         ["confirmed_btc_fills"], 1)

    def test_record_equity_is_separate_from_pnl(self):
        record_equity(
            self.path, "1000.50", at=datetime(2026, 11, 18, tzinfo=timezone.utc))
        self.assertEqual(fill_summary(self.path)["confirmed_btc_fills"], 0)
        with self.assertRaises(LedgerError):
            record_equity(self.path, "NaN")


if __name__ == "__main__":
    unittest.main()
