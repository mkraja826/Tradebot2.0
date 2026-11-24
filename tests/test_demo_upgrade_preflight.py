"""Offline regression tests for the no-order, no-AI VM restart gate."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from tradebot.delta import DEMO_API
from tradebot.demo_upgrade_preflight import audit_demo_upgrade
from tradebot.fire_execution import FireTradeStore


class FakeReadOnly:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, positions=None, orders=None, btc_lev=5, gold_lev=5,
                 realtime_positions=None, realtime_unavailable=False):
        self.positions = positions if positions is not None else []
        self.realtime_positions = (self.positions if realtime_positions is None
                                   else realtime_positions)
        self.realtime_unavailable = realtime_unavailable
        self.orders = orders if orders is not None else []
        self.leverage = {"BTCUSD": btc_lev, "XAUTUSD": gold_lev}
        self.calls = []

    def _request(self, method, path, *, auth=False, params=None):
        self.calls.append((method, path))
        assert method == "GET"
        if path == "/v2/positions/margined":
            assert params is None
            return {"result": self.positions}
        if path == "/v2/positions":
            assert params is not None and type(params.get("product_id")) is int
            if self.realtime_unavailable:
                raise ValueError("unavailable signed positions")
            candidates = self.realtime_positions
            if not isinstance(candidates, list):
                raise ValueError("invalid real-time fixture")
            matches = [p for p in candidates if p["product_id"] == params["product_id"]]
            return {"result": (matches[0] if matches else {"size": 0, "entry_price": "0"})}
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

    def test_unfiltered_realtime_request_is_never_sent(self):
        broker = FakeReadOnly()
        result = self.check(broker)
        self.assertTrue(result["safe_to_stage_execution_restart"])
        self.assertIn(("GET", "/v2/positions/margined"), broker.calls)
        self.assertEqual(broker.calls.count(("GET", "/v2/positions")), 2)
        self.assertEqual(result["realtime_fire_positions"],
                         {"BTCUSD": 0, "XAUTUSD": 0})

    def test_margin_snapshot_lag_cannot_hide_realtime_btc_position(self):
        broker = FakeReadOnly(
            positions=[],
            realtime_positions=[{"product_id": 27, "size": "-20"}])
        result = self.check(broker)
        self.assertEqual(result["broker_positions"], 0)
        self.assertEqual(result["realtime_fire_positions"]["BTCUSD"], -20)
        self.assertIn("realtime_market_exposure_btcusd", result["blockers"])
        self.assertFalse(result["safe_to_stage_execution_restart"])

    def test_realtime_endpoint_error_blocks_upgrade(self):
        result = self.check(FakeReadOnly(realtime_unavailable=True))
        self.assertIn("realtime_position_not_verified_btcusd", result["blockers"])
        self.assertFalse(result["safe_to_stage_execution_restart"])

    def test_unrelated_open_product_blocks_upgrade(self):
        result = self.check(FakeReadOnly(
            positions=[{"product_id": 999, "size": 5}]))
        self.assertEqual(result["broker_positions"], 1)
        self.assertFalse(result["safe_to_stage_execution_restart"])

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
        self.assertIn("broker_leverage_above_20x_btcusd", result["blockers"])
        self.assertIn("broker_leverage_above_20x_xautusd", result["blockers"])
        self.assertFalse(result["safe_to_enable_fire"])

    def test_20x_is_a_ceiling_not_permission_to_enable_fire(self):
        result = self.check(FakeReadOnly(btc_lev=20, gold_lev=5))
        self.assertEqual(result["leverage"], {"BTCUSD": "20", "XAUTUSD": "5"})
        self.assertNotIn("broker_leverage_above_20x_btcusd", result["blockers"])
        self.assertFalse(result["safe_to_enable_fire"])

    def test_old_unconfirmed_entry_blocks_staging_even_when_parent_flat(self):
        press = self.gold.reserve()
        self.gold.update(press, "flat_verified")
        with sqlite3.connect(self.gold.path) as db:
            db.execute(
                "CREATE TABLE fire_entries (press TEXT PRIMARY KEY, "
                "status TEXT NOT NULL, receipt TEXT NOT NULL)"
            )
            db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                       (press, "unconfirmed", "{}"))
        result = self.check()
        self.assertEqual(result["unresolved_fire_receipts"], 1)
        self.assertFalse(result["safe_to_stage_execution_restart"])
        self.assertIn("unresolved_fire_receipts", result["blockers"])
        # Read-only upgrade check must not change the stale row.
        with sqlite3.connect(self.gold.path) as db:
            self.assertEqual(db.execute("SELECT status FROM fire_entries").fetchone()[0],
                             "unconfirmed")

    def test_terminal_entry_with_flat_parent_does_not_block_staging(self):
        press = self.gold.reserve()
        self.gold.update(press, "flat_verified")
        with sqlite3.connect(self.gold.path) as db:
            db.execute(
                "CREATE TABLE fire_entries (press TEXT PRIMARY KEY, "
                "status TEXT NOT NULL, receipt TEXT NOT NULL)"
            )
            db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                       (press, "filled", "{}"))
        self.assertTrue(self.check()["safe_to_stage_execution_restart"])

    def test_orphaned_entry_refuses_upgrade_without_mutation(self):
        with sqlite3.connect(self.gold.path) as db:
            db.execute(
                "CREATE TABLE fire_entries (press TEXT PRIMARY KEY, "
                "status TEXT NOT NULL, receipt TEXT NOT NULL)"
            )
            db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                       ("orphan", "unconfirmed", "{}"))
        result = self.check()
        self.assertIn("fire_receipts_not_verified_xautusd", result["blockers"])
        self.assertFalse(result["safe_to_stage_execution_restart"])

    def test_live_account_client_is_rejected_without_network(self):
        fake = FakeReadOnly()
        fake.base_url = "https://api.india.delta.exchange"
        out = self.check(fake)
        self.assertFalse(out["safe_to_stage_execution_restart"])
        self.assertEqual(fake.calls, [])
        self.assertIn("read_only_delta_demo_client_required",out["blockers"])


if __name__ == "__main__":
    unittest.main()
