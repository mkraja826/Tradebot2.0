"""Offline and no-network tests for the read-only DEMO wallet probe."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from equity_fixtures import receipt_for
from tradebot.delta import DEMO_API
from tradebot.demo_wallet_transport_probe import probe_wallet_transport, main


class ReadOnlyWallet:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, *, value="1000", receipt=None, failure=None):
        self.calls = 0
        self.value = value
        self.receipt = receipt
        self.failure = failure

    def wallet_balances(self):
        self.calls += 1
        if self.failure:
            raise RuntimeError("SECRET_UPSTREAM_ERROR")
        return {"meta": {"net_equity": self.value},
                "equity_read_receipt": self.receipt}


class WalletTransportProbeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.exchange = ReadOnlyWallet(
            receipt=receipt_for("1000", self.now))

    def test_valid_receipt_still_never_allows_trading(self):
        result = probe_wallet_transport(self.exchange)
        self.assertEqual(result["status"],
                         "transport_receipt_verified_not_trade_authority")
        self.assertEqual(self.exchange.calls, 1)
        self.assertTrue(result["transport_receipt_verified"])
        for name in ("broker_valuation_timestamp_verified",
                     "opening_checkpoint_verified", "trade_authorized",
                     "safe_to_enable_fire", "ready_for_unattended_trading",
                     "local_ledger_mutations", "broker_order_mutations"):
            self.assertIs(result[name], False, name)
        self.assertNotIn("1000", json.dumps(result))
        self.assertNotIn("response_sha256", json.dumps(result))

    def test_wrong_broker_or_order_enabled_blocks_before_read(self):
        for attr, value in (("base_url", "https://live.invalid"),
                            ("allow_orders", True)):
            with self.subTest(attr=attr):
                original = getattr(self.exchange, attr)
                setattr(self.exchange, attr, value)
                result = probe_wallet_transport(self.exchange)
                self.assertEqual(result["reason"], "read_only_demo_client_required")
                self.assertEqual(self.exchange.calls, 0)
                setattr(self.exchange, attr, original)

    def test_missing_receipt_is_not_success(self):
        self.exchange.receipt = None
        result = probe_wallet_transport(self.exchange)
        self.assertEqual(result["reason"], "equity_read_receipt_missing")
        self.assertFalse(result["transport_receipt_verified"])

    def test_stale_response_is_denied(self):
        self.exchange.receipt = receipt_for("1000", self.now - timedelta(minutes=3))
        result = probe_wallet_transport(self.exchange)
        self.assertEqual(result["reason"], "broker_equity_read_stale")
        self.assertFalse(result["trade_authorized"])

    def test_inconsistent_equity_is_denied(self):
        self.exchange.value = "1001"
        result = probe_wallet_transport(self.exchange)
        self.assertEqual(result["reason"], "equity_read_value_mismatch")
        self.assertFalse(result["transport_receipt_verified"])

    def test_broker_exception_sanitized(self):
        self.exchange.failure = True
        result = probe_wallet_transport(self.exchange)
        self.assertEqual(result["reason"], "wallet_read_unavailable")
        self.assertNotIn("SECRET_UPSTREAM_ERROR", json.dumps(result))
        self.assertEqual(self.exchange.calls, 1)

    def test_invalid_body_is_fail_closed(self):
        self.exchange.wallet_balances = lambda: {"meta": None}
        result = probe_wallet_transport(self.exchange)
        self.assertEqual(result["reason"], "wallet_response_unverified")

    def test_missing_credentials_cli_does_not_contact_exchange(self):
        with patch.dict("os.environ", {
            "DELTA_DEMO_API_KEY": "", "DELTA_DEMO_API_SECRET": "",
        }):
            with patch("tradebot.demo_wallet_transport_probe.DeltaDemo") as cls:
                with patch("builtins.print"):
                    self.assertEqual(main([]), 2)
                cls.assert_not_called()

    def test_cli_enforces_no_order_mutation_client(self):
        with patch.dict("os.environ", {
            "DELTA_DEMO_API_KEY": "fixture",
            "DELTA_DEMO_API_SECRET": "fixture",
        }):
            with patch("tradebot.demo_wallet_transport_probe.DeltaDemo") as cls:
                cls.return_value = self.exchange
                with patch("builtins.print"):
                    self.assertEqual(main([]), 0)
                cls.assert_called_once_with(
                    api_key="fixture", api_secret="fixture", allow_orders=False)


if __name__ == "__main__":
    unittest.main()
