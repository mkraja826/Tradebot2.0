import unittest
from unittest.mock import Mock
from tradebot.dashboard import _cashflows
from tradebot.delta import DeltaDemo, DeltaError


class WalletPerformanceTests(unittest.TestCase):
    def test_signed_postings_keep_assets_separate(self):
        rows = [dict(asset_symbol=asset, amount=amount, transaction_type=kind)
                for asset, amount, kind in [
                    ("USD","200","deposit"),("USD","10","cashflow"),
                    ("USD","-1.25","commission"),("USD","-.50","funding"),
                    ("INR","-2","liquidation_fee")]]
        totals = _cashflows(rows)
        self.assertEqual(totals["USD"]["net"], "8.25")
        self.assertEqual(totals["INR"]["net"], "-2")

    def test_incomplete_pagination_cannot_report_performance(self):
        client = DeltaDemo()
        client._request = Mock(return_value={"result":[],"meta":{"after":"repeat"}})
        with self.assertRaises(DeltaError):
            client.wallet_postings(1,2)
