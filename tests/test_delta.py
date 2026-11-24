import hashlib
import hmac
import unittest

from tradebot.delta import DeltaDemo, DeltaError, DEMO_API, is_btc_contract, signature


class TestDeltaDemo(unittest.TestCase):
    def test_signature(self):
        data = "POST1700000000/v2/orders{}"
        self.assertEqual(signature("secret", "POST", "1700000000", "/v2/orders", "", "{}"),
                         hmac.new(b"secret", data.encode(), hashlib.sha256).hexdigest())

    def test_demo_only(self):
        exchange = DeltaDemo("demo", "secret")
        self.assertEqual(exchange.base_url, DEMO_API)
        self.assertEqual(DEMO_API, "https://cdn-ind.testnet.deltaex.org")

    def test_order_mutations_off(self):
        with self.assertRaises(DeltaError):
            DeltaDemo("demo", "secret").place_order(
                product={"id": 1, "symbol": "BTCUSD",
                         "contract_type": "perpetual_futures", "state": "live"},
                side="buy", size=1, client_order_id="tb2-testing")

    def test_reject_other_asset(self):
        self.assertFalse(is_btc_contract(
            {"id": 2, "symbol": "ETHUSD", "contract_type": "perpetual_futures", "state": "live"}))
        self.assertTrue(is_btc_contract(
            {"id": 1, "symbol": "BTCUSD", "contract_type": "perpetual_futures", "state": "live"}))

    def test_reject_expired_option(self):
        self.assertFalse(is_btc_contract(
            {"id": 3, "symbol": "C-BTC-30000-141126",
             "contract_type": "call_options", "state": "expired"}))

    def test_validates_order_quantity(self):
        with self.assertRaises(ValueError):
            DeltaDemo("demo", "secret", True).place_order(
                product={"id": 1, "symbol": "BTCUSD",
                         "contract_type": "perpetual_futures", "state": "live"},
                side="buy", size=0, client_order_id="tb2-testing")

    def test_path_guard(self):
        with self.assertRaises(ValueError):
            DeltaDemo()._request("GET", "https://api.india.delta.exchange/v2/products")
