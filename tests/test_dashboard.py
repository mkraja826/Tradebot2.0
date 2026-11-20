"""Offline read-only dashboard tests. No broker, AI, or external requests."""
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sqlite3
from threading import Thread
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from tradebot.dashboard import (
    DashboardData, _events, _ledger, _runtime, create_handler,
)
from tradebot.journal import record
from tradebot.runner import BotRunner, RunnerConfig


class FakeMarket:
    api_key = "dummy-key"
    api_secret = "dummy-secret"
    allow_orders = False

    def ticker(self, symbol):
        assert symbol == "BTCUSD"
        return {
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "quotes": {"best_bid": "95200", "best_ask": "95204"},
            "mark_price": "95202",
        }

    def btc_positions(self):
        return [{"size": "2", "product_symbol": "BTCUSD"},
                {"size": "0", "product_symbol": "C-BTC-111"}]

    def open_orders(self):
        return [{"product_symbol": "BTCUSD"}]

    def wallet_balances(self):
        return {"meta": {"net_equity": "503.5"}, "balances": []}

    def place_order(self, **kwargs):
        raise AssertionError("Dashboard must never submit an order")


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_remote_snapshot_is_read_only_and_quote_is_validated(self):
        exchange = FakeMarket()
        data = DashboardData(self.dir, exchange=exchange)
        data._load_remote()
        obj = data.snapshot()
        self.assertEqual(obj["live"]["market"]["status"], "fresh")
        self.assertEqual(obj["live"]["account"]["btc_open_positions"], 1)
        self.assertEqual(obj["live"]["account"]["account_open_orders"], 1)
        self.assertEqual(obj["dashboard_mode"], "read_only")
        self.assertEqual(obj["live"]["account"]["net_equity"], "503.5")

    def test_secret_in_journal_is_not_exposed(self):
        record(str(self.dir / "trades.jsonl"), "ai_decision",
               {"strategy": "WAIT", "rationale": "No edge",
                "TB_API_KEY": "sensitive-value",
                "api_key": "also-secret", "mode": "observe"})
        events = _events(self.dir / "trades.jsonl")
        self.assertEqual(len(events), 1)
        serialized = json.dumps(events)
        self.assertIn("WAIT", serialized)
        self.assertNotIn("sensitive-value", serialized)
        self.assertNotIn("also-secret", serialized)

    def test_missing_ledger_has_no_fabricated_pnl(self):
        ledger = _ledger(self.dir / "none.sqlite")
        self.assertEqual(ledger["confirmed_btc_fills"], 0)
        self.assertFalse(ledger["is_realized_pnl"])
        self.assertEqual(ledger["equity_points"], [])

    def test_empty_existing_ledger_has_no_fake_performance(self):
        file = self.dir / "confirmed-fills.sqlite"
        with sqlite3.connect(file) as db:
            db.execute("CREATE TABLE fills (id TEXT, commission TEXT, settling_asset TEXT)")
            db.execute("CREATE TABLE equity_snapshots (captured_at TEXT, net_equity TEXT)")
        ledger = _ledger(file)
        self.assertEqual(ledger["confirmed_btc_fills"], 0)
        self.assertEqual(ledger["equity_points"], [])

    def test_runtime_requires_recent_heartbeat(self):
        runtime_path = self.dir / "runtime.json"
        self.assertEqual(_runtime(runtime_path)["status"], "not_started")
        raw = {"updated_at": (datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(),
               "mode": "demo", "schedule": "crypto-24x7", "action": "preview"}
        runtime_path.write_text(json.dumps(raw))
        self.assertEqual(_runtime(runtime_path)["status"], "stale")
        raw["updated_at"] = datetime.now(timezone.utc).isoformat()
        runtime_path.write_text(json.dumps(raw))
        self.assertEqual(_runtime(runtime_path)["status"], "running")
        raw["schedule"] = "nyse-cash-observe"
        raw["action"] = "nyse_cash_closed_no_ai"
        raw["next_scan"] = None
        runtime_path.write_text(json.dumps(raw))
        self.assertEqual(_runtime(runtime_path)["schedule"], "nyse-cash-observe")
        self.assertEqual(_runtime(runtime_path)["action"], "nyse_cash_closed_no_ai")
        self.assertIsNone(_runtime(runtime_path)["next_scan"])
        raw["action"] = "stopped"
        runtime_path.write_text(json.dumps(raw))
        self.assertEqual(_runtime(runtime_path)["status"], "stopped")

    def test_runner_writes_non_secret_atomic_heartbeat(self):
        fake = Mock()
        fake.base_url = "https://cdn-ind.testnet.deltaex.org"
        runner = BotRunner(fake, Mock(), config=RunnerConfig(
            mode="observe", journal_path=str(self.dir / "trades.jsonl")))
        runner._dashboard_heartbeat("cooldown")
        raw = json.loads((self.dir / "runtime.json").read_text())
        self.assertEqual(raw["mode"], "observe")
        self.assertEqual(raw["action"], "cooldown")
        self.assertNotIn("api_key", json.dumps(raw).lower())
        self.assertEqual((self.dir / "runtime.json").stat().st_mode & 0o777, 0o600)

    def test_local_routes_and_host_policy(self):
        class Stub:
            root = self.dir
            def snapshot(self):
                return {"dashboard_mode": "read_only", "environment": "delta-india-demo"}
        server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(Stub()))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        host, port = server.server_address
        base = "http://127.0.0.1:" + str(port)
        with urlopen(base + "/") as res:
            html = res.read().decode()
            self.assertEqual(res.status, 200)
            self.assertIn("Tradebot 2.0", html)
            self.assertIn("frame-ancestors 'none'", res.headers["Content-Security-Policy"])
        with urlopen(base + "/api/overview") as res:
            payload = json.load(res)
            self.assertEqual(payload["dashboard_mode"], "read_only")
        with urlopen(base + "/api/risk/checkpoints") as res:
            risk = json.load(res)
            self.assertEqual(res.status, 200)
            self.assertEqual(risk["status"], "evidence_unavailable")
            self.assertFalse(risk["checkpoint_prerequisites_met"])
            self.assertFalse(risk["trade_authorized"])
            self.assertEqual(risk["mode"], "read_only")
        self.assertFalse((self.dir / "fire-equity-risk.sqlite").exists())
        for route in ("/styles.css", "/app.js"):
            with urlopen(base + route) as res:
                self.assertEqual(res.status, 200)
                self.assertTrue(res.read())
        with self.assertRaises(HTTPError) as blocked:
            urlopen(Request(base + "/", headers={"Host": "evil.example"}))
        self.assertEqual(blocked.exception.code, 403)
        with self.assertRaises(HTTPError) as write_attempt:
            urlopen(Request(base + "/api/overview", data=b"{}", method="POST"))
        self.assertEqual(write_attempt.exception.code, 405)

    def test_static_assets_have_no_external_cdn_requirement(self):
        root = Path(__file__).resolve().parents[1] / "src/tradebot/dashboard_static"
        html = (root / "index.html").read_text()
        css = (root / "styles.css").read_text()
        js = (root / "app.js").read_text()
        self.assertIn('src="/app.js"', html)
        self.assertIn('href="/styles.css"', html)
        # The SVG namespace is an identifier, not a network request.
        self.assertNotIn('src="http', html)
        self.assertNotIn('href="http', html)
        self.assertNotIn('@import', css)
        self.assertNotIn('fetch("http', js)
        self.assertNotIn('fetch("https', js)
        self.assertNotIn("innerHTML", js)
        self.assertIn('fetch("/api/overview"', js)
        self.assertIn('id="equity-risk-banner"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('fetch("/api/risk/checkpoints"', js)
        self.assertIn("renderEquityCheckpointRisk(null)", js)
        self.assertIn("data-state", css)
        self.assertNotIn('fetch("/api/risk/checkpoints", {method:"POST"', js)


if __name__ == "__main__":
    unittest.main()
