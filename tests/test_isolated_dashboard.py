"""Two independent child-account dashboard cards; no trading or model access."""
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os
import sqlite3
import unittest

from tradebot.dashboard import create_handler
from tradebot.delta import DEMO_API
from tradebot.isolated_dashboard import (
    IsolatedAccountsDashboard, _read_keyfile, _fire_receipts, _sanitized_positions,
    _signed_brackets,
)


class FakeBroker:
    mutations = []
    calls = []

    def __init__(self, *, api_key, api_secret, allow_orders):
        if allow_orders:
            self.mutations.append("enabled_orders")
        self.allow_orders = allow_orders
        self.base_url = DEMO_API
        self.key = api_key

    def _request(self, method, path, *, auth=False, **kwargs):
        self.calls.append((self.key, method, path))
        if method != "GET":
            self.mutations.append(path)
            raise AssertionError("Broker mutation attempted")
        if path == "/v2/users/trading_preferences":
            return {"result": {"user_id": {
                "PARENT": 100, "BTC_CHILD": 101, "GOLD_CHILD": 102,
            }[self.key]}}
        if path == "/v2/sub_accounts":
            if self.key != "PARENT":
                raise AssertionError("Child cannot supply parent's signed roster")
            return {"result": [
                {"id": 101, "account_name": "BTC Demo", "margin_mode": "isolated"},
                {"id": 102, "account_name": "Gold Demo", "margin_mode": "isolated"},
            ]}
        if path == "/v2/positions/margined":
            return {"result": ([
                {"product_symbol": "BTCUSD", "product_id": 3,
                 "size": "2", "entry_price": "70000",
                 "unrealized_pnl": "-0.24"}
            ] if self.key == "BTC_CHILD" else [])}
        raise ValueError("Unexpected broker GET")

    def open_orders(self):
        self.calls.append((self.key, "GET", "/v2/orders"))
        return ([{"id": "id", "product_id": 3}]
                if self.key == "BTC_CHILD" else [])

    def wallet_balances(self):
        self.calls.append((self.key, "GET", "/v2/wallet/balances"))
        return {"meta": {"net_equity":
                        "84.6" if self.key == "BTC_CHILD" else "137.5"}}


class IsolatedDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        self.keys = Path(self.tmp.name) / "config"
        self.keys.mkdir()
        FakeBroker.calls = []
        FakeBroker.mutations = []
        for label, db_name in (
                ("btc-isolated", "fire-ops.sqlite"),
                ("gold-isolated", "fire-xaut.sqlite")):
            root = self.root / label
            root.mkdir()
            root.chmod(0o700)
            with sqlite3.connect(root / db_name) as db:
                db.execute("CREATE TABLE fire_requests("
                           "status TEXT, result TEXT, created_at TEXT)")
                if label == "gold-isolated":
                    db.execute("INSERT INTO fire_requests VALUES(?,?,?)",(
                        "protected_active", json.dumps({
                            "model": "tb-deepseek-v4-1-flash",
                            "direction": "LONG", "contracts": 2,
                            "orders_submitted": True,
                            "protection_verified": True,
                            "secret": "DO_NOT_SHOW_THIS",
                        }),"2026-11-23T06:17:00+00:00"))
            attempts = "btc-auto-demo.sqlite" if label=="btc-isolated" else "gold-auto-demo.sqlite"
            table = "btc_auto_attempts" if label=="btc-isolated" else "gold_auto_attempts"
            with sqlite3.connect(root / attempts) as db:
                db.execute("CREATE TABLE "+table+
                           " (status TEXT,requested_at INTEGER)")
                db.execute("INSERT INTO "+table+" VALUES (?,?)",("protected_active",1000000))
            with sqlite3.connect(root / "fire-equity-risk.sqlite") as db:
                db.execute("CREATE TABLE equity_evidence("
                           "observed_us INTEGER,equity_usd TEXT)")
                db.execute("INSERT INTO equity_evidence VALUES (?,?)",(
                    1771848000000000, "100"))
        from tradebot.gold_autonomous_demo import ARM_CONTENT
        arm = self.keys / "gold-isolated-autonomous-armed"
        arm.write_text(ARM_CONTENT+"\n")
        arm.chmod(0o600)

    @staticmethod
    def credentials(path):
        value = "BTC_CHILD" if path.name.startswith("btc-") else "GOLD_CHILD"
        return {"DELTA_DEMO_API_KEY":value,"DELTA_DEMO_API_SECRET":"TEST"}

    def dashboard(self):
        return IsolatedAccountsDashboard(
            self.root, key_dir=self.keys,
            client_factory=FakeBroker,
            credential_loader=self.credentials,
            service_check=lambda unit: True)

    def test_signed_child_accounts_do_not_mix_btc_and_gold(self):
        with patch.dict(os.environ, {"DELTA_DEMO_API_KEY": "PARENT",
                                     "DELTA_DEMO_API_SECRET": "TEST"}):
            report = self.dashboard().refresh()
        self.assertEqual(report["mode"],"read_only")
        btc,gold=report["accounts"]["BTC"],report["accounts"]["GOLD"]
        self.assertEqual(btc["status"],"connected")
        self.assertEqual(gold["status"],"connected")
        self.assertEqual(btc["margin_mode"],"isolated_verified")
        self.assertEqual(gold["margin_mode"],"isolated_verified")
        self.assertEqual(btc["live_position_count"],1)
        self.assertEqual(btc["open_orders"],1)
        self.assertEqual(gold["live_position_count"],0)
        self.assertEqual(gold["open_orders"],0)
        self.assertEqual(btc["net_equity"],"84.6")
        self.assertEqual(gold["net_equity"],"137.5")
        self.assertEqual(gold["fire"]["total"],1)
        self.assertEqual(btc["fire"]["total"],0)
        self.assertEqual(gold["fire"]["recent"][0]["model"],"tb-deepseek-v4-1-flash")
        self.assertIn("flat account",gold["reconciliation_warning"])
        self.assertEqual(gold["attempts"]["total"],1)
        self.assertFalse(report["realized_pnl_verified"])
        self.assertIsNone(gold["realized_pnl"])
        self.assertFalse(FakeBroker.mutations)
        self.assertFalse(any(k[1]!="GET" for k in FakeBroker.calls))
        self.assertNotIn("DO_NOT_SHOW_THIS",json.dumps(report))
        self.assertNotIn("BTC_CHILD",json.dumps(report))
        self.assertNotIn("GOLD_CHILD",json.dumps(report))
        self.assertNotIn("PARENT",json.dumps(report))

    def test_signing_failure_never_invents_empty_positions(self):
        with patch.dict(os.environ, {"DELTA_DEMO_API_KEY": "PARENT",
                                     "DELTA_DEMO_API_SECRET": "TEST"}):
            snap=self.dashboard()
            def bad(path):
                return {"DELTA_DEMO_API_KEY":"UNKNOWN",
                        "DELTA_DEMO_API_SECRET":"TEST"}
            snap.credential_loader=bad
            report=snap.refresh()
        for acct in report["accounts"].values():
            self.assertEqual(acct["status"],"broker_unavailable")
            self.assertIsNone(acct["live_position_count"])
            self.assertIsNone(acct["open_orders"])
            self.assertIsNone(acct["net_equity"])
            self.assertNotEqual(acct["margin_mode"],"isolated_verified")

    def test_unverified_product_never_mislabelled_gold(self):
        items=_sanitized_positions([{
            "size":"3","product_symbol":"ETHUSD","entry_price":"4200"}],
            "XAUTUSD")
        self.assertEqual(items[0]["symbol"],"OTHER DERIVATIVE")
        with self.assertRaises(ValueError):
            _sanitized_positions([{"size": "not-a-number"}],"BTCUSD")

    def test_signed_pending_brackets_for_actual_broker_position(self):
        positions=_sanitized_positions([{
            "size":"2","product_symbol":"BTCUSD","entry_price":"61523",
            "mark_price":"61477.56","liquidation_price":"49372.20",
            "unrealized_pnl":"-0.2"}],"BTCUSD")
        orders=[
            {"product_symbol":"BTCUSD","side":"sell","reduce_only":True,
             "state":"pending","stop_order_type":"stop_loss_order",
             "stop_price":"61280","size":2,"client_order_id":"PRIVATE"},
            {"product_symbol":"BTCUSD","side":"sell","reduce_only":True,
             "state":"pending","stop_order_type":"take_profit_order",
             "stop_price":"61840","size":2,"client_order_id":"PRIVATE"}
        ]
        _signed_brackets(positions,orders)
        self.assertEqual(positions[0]["protection"]["status"],
                         "signed_pending_bracket")
        self.assertEqual(positions[0]["protection"]["stop_loss"],"61280")
        self.assertEqual(positions[0]["protection"]["take_profit"],"61840")
        self.assertEqual(positions[0]["mark"],"61477.56")
        self.assertEqual(positions[0]["liquidation"],"49372.20")
        self.assertNotIn("PRIVATE",json.dumps(positions))

    def test_missing_wrong_or_duplicate_broker_exits_never_claim_protection(self):
        template={"size":"1","product_symbol":"XAUTUSD","entry_price":"4500"}
        ok=[
            {"product_symbol":"XAUTUSD","side":"sell","reduce_only":True,
             "state":"pending","stop_order_type":"stop_loss_order",
             "stop_price":"4480","size":1},
            {"product_symbol":"XAUTUSD","side":"sell","reduce_only":True,
             "state":"pending","stop_order_type":"take_profit_order",
             "stop_price":"4530","size":1},
        ]
        for invalid in (ok[:1],ok+[dict(ok[0])],
                        [dict(ok[0],reduce_only=False),ok[1]],
                        [dict(ok[0],state="cancelled"),ok[1]],
                        [dict(ok[0],side="buy"),ok[1]],
                        [dict(ok[0],size=0),ok[1]],
                        [dict(ok[0],stop_price="4550"),ok[1]],
                        [dict(ok[0],product_symbol="BTCUSD"),ok[1]]):
            with self.subTest(invalid=invalid):
                view=_sanitized_positions([template],"XAUTUSD")
                _signed_brackets(view,invalid)
                self.assertEqual(view[0]["protection"]["status"],"unverified")
                self.assertIsNone(view[0]["protection"]["stop_loss"])
                self.assertIsNone(view[0]["protection"]["take_profit"])

    def test_local_fire_reports_do_not_expose_secrets(self):
        path=self.root/"gold-isolated"
        outcome=_fire_receipts(path,"fire-xaut.sqlite")
        self.assertEqual(outcome["recent"][0]["status"],"protected_active")
        self.assertNotIn("secret",outcome["recent"][0])
        self.assertFalse(outcome["realized_pnl_verified"])

    def test_credential_file_mode_and_symlink_rejection(self):
        f=self.keys/"btc-demo-keys.env"
        f.write_text("DELTA_DEMO_API_KEY=dummy\nDELTA_DEMO_API_SECRET=dummysecret\n")
        f.chmod(0o644)
        with self.assertRaises(ValueError):
            _read_keyfile(f)
        f.chmod(0o600)
        self.assertEqual(_read_keyfile(f)["DELTA_DEMO_API_KEY"],"dummy")
        alias=self.keys/"alias.env"
        alias.symlink_to(f)
        with self.assertRaises(ValueError):
            _read_keyfile(alias)

    def test_read_only_http_endpoint_and_write_rejected(self):
        class Stub:
            root=self.root
            class Isolated:
                def snapshot(self):
                    return {"mode":"read_only","source":"isolated_child_accounts",
                            "accounts":{"BTC":{"status":"connected"},
                                        "GOLD":{"status":"connected"}}}
            isolated_accounts=Isolated()
        server=ThreadingHTTPServer(
            ("127.0.0.1",0),create_handler(Stub()))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        Thread(target=server.serve_forever,daemon=True).start()
        base="http://127.0.0.1:"+str(server.server_address[1])
        with urlopen(base+"/api/isolated/overview") as r:
            body=json.load(r)
            self.assertEqual(body["accounts"]["GOLD"]["status"],"connected")
            self.assertEqual(r.headers["Cache-Control"],"no-store")
        with self.assertRaises(HTTPError) as bad:
            urlopen(Request(base+"/api/isolated/overview",
                            data=b"{}",method="POST"))
        self.assertEqual(bad.exception.code,405)
        with urlopen(base+"/isolated.js") as r:
            self.assertIn("read_only",r.read().decode())
        with urlopen(base+"/") as r:
            self.assertIn("isolated-grid",r.read().decode())


if __name__=="__main__":
    unittest.main()
