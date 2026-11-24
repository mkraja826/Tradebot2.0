import hashlib
import hmac
import unittest
from unittest.mock import patch

from tradebot.delta import DeltaDemo, DeltaError, DeltaReadError, DEMO_API, is_btc_contract, signature


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

    def test_malformed_signed_wallet_response_is_sanitized(self):
        for raw in (b"private upstream response", b"[]", b"null", bytes([255])):
            with self.subTest(raw=raw), patch("tradebot.delta.urlopen") as request:
                response = request.return_value.__enter__.return_value
                response.read.return_value = raw
                response.headers = {}
                with self.assertRaises(DeltaReadError) as error:
                    DeltaDemo("fixture", "secret").wallet_balances()
                self.assertEqual(error.exception.code, "broker_equity_unavailable")
                self.assertNotIn("private upstream response", str(error.exception))
                self.assertEqual(request.call_args.args[0].get_method(), "GET")

    def test_malformed_public_response_uses_broker_error(self):
        with patch("tradebot.delta.urlopen") as request:
            response = request.return_value.__enter__.return_value
            response.read.return_value = b"private upstream response"
            with self.assertRaises(DeltaError) as error:
                DeltaDemo().ticker("BTCUSD")
            self.assertEqual(str(error.exception), "Malformed demo exchange response")
