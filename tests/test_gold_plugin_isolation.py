"""Gold plugin read paths never return legacy parent-account FIRE receipts."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID
import json
import sqlite3
import unittest

from tradebot.isolated_dashboard import isolated_gold_fire_history


FIRE_ID = "123456781234123412341234567890ab"


class GoldIsolatedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / "gold-isolated"
        root.mkdir()
        with sqlite3.connect(root / "fire-xaut.sqlite") as db:
            db.execute(
                "CREATE TABLE fire_requests("
                "press TEXT,status TEXT,result TEXT,created_at TEXT,updated_at TEXT)")
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?,?)", (
                FIRE_ID, "flat_verified", json.dumps({
                    "model": "tb-deepseek-v4-1-flash",
                    "orders_submitted": True,
                    "broker_order_id": "21800000",
                    "direction": "LONG",
                    "thesis": "A market-only entry thesis",
                    "api_key": "MUST_NOT_LEAK",
                    "reason_code": "verified_no_position_or_orders",
                }), "2026-11-23T12:00:00+00:00",
                "2026-11-23T12:03:00+00:00"))

    def test_history_and_exact_id_are_isolated_and_sanitized(self):
        history = isolated_gold_fire_history(self.tmp.name)
        self.assertEqual(history["source"], "gold_isolated_fire_receipts")
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["receipts"][0]["id"], FIRE_ID)
        self.assertNotIn("MUST_NOT_LEAK", str(history))
        reviewed = isolated_gold_fire_history(self.tmp.name, press=FIRE_ID)
        self.assertEqual(reviewed["receipts"][0]["broker_order_id"], "21800000")
        self.assertEqual(
            isolated_gold_fire_history(self.tmp.name, press="a" * 32)["receipts"], [])
        self.assertEqual(isolated_gold_fire_history(self.tmp.name, page=1)["receipts"], [])

    def test_no_fallback_to_legacy_parent_or_invalid_identifier(self):
        with self.assertRaises(ValueError):
            isolated_gold_fire_history(Path(self.tmp.name) / "missing")
        with self.assertRaises(ValueError):
            isolated_gold_fire_history(self.tmp.name, press="../../fire-xaut.sqlite")


@unittest.skipUnless(find_spec("mcp"), "MCP is optional")
class GoldPluginRoutingTests(unittest.TestCase):
    def test_gold_status_history_review_uses_child_account(self):
        from tradebot.chat_plugin import market_status, fire_history, review_fire
        calls = []

        def fake(path):
            calls.append(path)
            if path.startswith("/api/chart-desk?"):
                return {"quote": {"price": 3600}, "historical_levels": {}}
            if path.startswith("/api/isolated/fire/"):
                return {
                    "source": "gold_isolated_fire_receipts", "total": 1,
                    "receipts": [{"id": FIRE_ID, "status": "flat_verified"}]}
            if path == "/api/isolated/overview":
                return {
                    "source": "isolated_child_accounts",
                    "checked_at": "2026-11-23T12:00:00Z",
                    "accounts": {"GOLD": {
                        "worker_active": True, "halted": False,
                        "status": "connected", "positions": []}}}
            if path.startswith("/api/isolated/review/"):
                return {"source": "gold_isolated_fire_receipts",
                        "receipt": {"id": FIRE_ID}}
            raise AssertionError("Unexpected path: " + path)

        with patch("tradebot.chat_plugin.dashboard", side_effect=fake):
            status = market_status("XAUTUSD")
            history = fire_history("XAUTUSD", 0)
            reviewed = review_fire("XAUTUSD", UUID(FIRE_ID))
        self.assertEqual(status["source"], "gold_isolated_subaccount")
        self.assertEqual(status["history_total"], 1)
        self.assertEqual(history["receipts"][0]["id"], FIRE_ID)
        self.assertEqual(reviewed["receipt"]["id"], FIRE_ID)
        self.assertNotIn("/api/fire/XAUTUSD", calls)
        self.assertFalse(any("/api/plugin/review/XAUTUSD/" in x for x in calls))

    def test_btc_route_remains_legacy_and_unchanged(self):
        from tradebot.chat_plugin import market_status, fire_history
        def fake(path):
            if path.startswith("/api/chart-desk?"):
                return {"quote": {}, "account": {"positions": []},
                        "historical_levels": {}, "trades": []}
            self.assertEqual(path, "/api/fire")
            return {"status": "flat_verified"}
        with patch("tradebot.chat_plugin.dashboard", side_effect=fake):
            self.assertEqual(market_status("BTCUSD")["latest_fire"]["status"],
                             "flat_verified")
            self.assertEqual(fire_history("BTCUSD", 0)["receipts"], [])


if __name__ == "__main__":
    unittest.main()
