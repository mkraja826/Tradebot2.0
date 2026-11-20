"""Offline regression tests for the no-order, no-AI VM restart gate."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from tradebot.delta import DEMO_API
from tradebot.demo_upgrade_preflight import audit_demo_upgrade
from tradebot.fire_execution import FireTradeStore


class FakeReadOnly:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, positions=None, orders=None, btc_lev=5, gold_lev=5):
        self.positions = positions if positions is not None else []
        self.orders = orders if orders is not None else []
        self.leverage = {"BTCUSD": btc_lev, "XAUTUSD": gold_lev}
        self.calls = []

    def _request(self, method, path, *, auth=False):
        self.calls.append((method, path))
        assert method == "GET"
        if path == "/v2/positions":
            return {"result": self.positions}
        if path.startswith("/v2/products/") and path.endswith("/orders/leverage"):
            id_ = int(path.split("/")[3])
            symbol = {27: "BTCUSD", 82: "XAUTUSD"}[id_]
            return {"result": {"product_id": id_, "leverage": self.leverage[symbol]}}
        if path.startswith("/v2/products/"):
            symbol = path.rsplit("/",1)[1]
            return {"result": {
                "id": {"BTCUSD":27,"XAUTUSD":82}[symbol],
                "symbol":symbol, "contract_type":"perpetual_futures",
                "notional_type":"vanilla", "settling_asset":{"symbol":"USD"},
            }}
        raise AssertionError("Unexpected request")

    def open_orders(self):
        self.calls.append(("GET", "/v2/orders"))
        return self.orders


class DemoUpgradePreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.btc = FireTradeStore(self.root / "fire-ops.sqlite")
        self.gold = FireTradeStore(self.root / "fire-xaut.sqlite")

    def check(self, fake=None):
        fake = fake or FakeReadOnly()
        return audit_demo_upgrade(fake, self.root)

    def test_flat_terminal_receipts_admit_staging_only(self):
        btc = self.btc.reserve()
        self.btc.update(btc, "flat_verified")
        gold = self.gold.reserve()
        self.gold.update(gold, "rejected_no_order")
        fake = FakeReadOnly()
        result = self.check(fake)
        self.assertTrue(result["safe_to_stage_execution_restart"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertEqual(result["ai_calls"], 0)
        self.assertFalse(result["order_mutations"])
        self.assertTrue(all(method=="GET" for method, _ in fake.calls))

    def test_open_btc_and_gold_accounts_block_upgrade(self):
        broker = FakeReadOnly(positions=[
            {"product_id":27,"size":"-30"},
            {"product_id":82,"size":"-200"}])
        result = self.check(broker)
        self.assertFalse(result["safe_to_stage_execution_restart"])
        self.assertEqual(result["broker_positions"],2)
        self.assertIn("account_has_open_positions",result["blockers"])

    def test_open_orders_and_unknown_receipt_block(self):
        btc = self.btc.reserve()
        self.btc.update(btc,"exposure_unknown")
        result = self.check(FakeReadOnly(orders=[{"id":5}]))
        self.assertIn("account_has_open_orders", result["blockers"])
        self.assertIn("unresolved_fire_receipts", result["blockers"])
        self.assertFalse(result["safe_to_stage_execution_restart"])

    def test_missing_file_or_unreadable_positions_fails_closed(self):
        self.gold.path.unlink()
        fake = FakeReadOnly(positions={"size":0})
        result = self.check(fake)
        self.assertIn("account_positions_not_verified", result["blockers"])
        self.assertIn("fire_receipts_not_verified_xautusd", result["blockers"])
        self.assertFalse(result["safe_to_stage_execution_restart"])

    def test_leverage_100x_reported_and_fire_remains_disabled(self):
        result = self.check(FakeReadOnly(btc_lev=100,gold_lev=100))
        self.assertTrue(result["safe_to_stage_execution_restart"])
        self.assertIn("broker_leverage_above_5x_btcusd",result["blockers"])
        self.assertIn("broker_leverage_above_5x_xautusd",result["blockers"])
        self.assertFalse(result["safe_to_enable_fire"])

    def test_live_account_client_is_rejected_without_network(self):
        fake = FakeReadOnly()
        fake.base_url = "https://api.india.delta.exchange"
        out = self.check(fake)
        self.assertFalse(out["safe_to_stage_execution_restart"])
        self.assertEqual(fake.calls, [])
        self.assertIn("read_only_delta_demo_client_required",out["blockers"])


if __name__ == "__main__":
    unittest.main()
