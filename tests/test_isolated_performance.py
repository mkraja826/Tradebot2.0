"""No fabricated P&L: signed broker cashflow and strict closed-FIRE evidence."""
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import sqlite3
import unittest

from tradebot.dashboard import create_handler
from tradebot.delta import DEMO_API
from tradebot.isolated_performance import (
    _cashflows, collect_account_performance, IsolatedPerformanceDashboard)
from tradebot.fire_reconciliation import ReconciliationError


class CompleteReadOnlyBroker:
    base_url=DEMO_API
    allow_orders=False

    def __init__(self, now):
        self.now=now
        self.calls=[]

    def _request(self, method, path, **kwargs):
        self.calls.append((method,path))
        if method != "GET":
            raise AssertionError("Financial dashboard may only GET")
        if path == "/v2/products/BTCUSD":
            return {"result":{"id":12,"symbol":"BTCUSD",
                "contract_type":"perpetual_futures"}}
        raise ValueError("Unexpected fake GET")

    def product_fills(self, product_id, *, start_time_us, end_time_us):
        assert product_id == 12
        assert end_time_us - start_time_us == 7*86400*1000000
        return []

    def wallet_postings(self,start,end):
        assert end-start == 7*86400*1000000
        stamp=int((self.now-timedelta(minutes=40)).timestamp()*1000000)
        result=[]
        for i,(kind,amount) in enumerate((
            ("cashflow","15.00"), ("commission","-1.00"),
            ("funding","0.20"),("sub_account_transfer","500"),
            ("external_deposit","1000"))):
            result.append({"id":str(500+i),"created_at":stamp+i,
                "asset_symbol":"USD","transaction_type":kind,
                "amount":amount, "product_id":None,"meta_data":{}})
        return result


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"btc-isolated"
        self.root.mkdir()
        self.now=datetime(2026,11,23,8,0,tzinfo=timezone.utc)
        with sqlite3.connect(self.root/"fire-ops.sqlite") as db:
            db.execute("CREATE TABLE fire_requests("
                       "press TEXT,created_at TEXT,status TEXT,result TEXT)")
            for i,(status,details) in enumerate((
                ("rejected_no_order",{"orders_submitted":False}),
                ("protected_active",{"contracts":2,"direction":"LONG",
                                    "broker_order_id":100}),
                ("flat_verified",{"contracts":1,"direction":"SHORT",
                                  "broker_order_id":101}))):
                stamp=(self.now-timedelta(hours=i+1)).isoformat()
                db.execute("INSERT INTO fire_requests VALUES (?,?,?,?)",
                    (format(i+1,"032x"),stamp,status,json.dumps(details)))

    def test_signed_wallet_cashflows_exclude_transfers_and_deposits(self):
        broker=CompleteReadOnlyBroker(self.now)
        report=collect_account_performance(
            broker,self.root,"BTCUSD",now=self.now)
        self.assertEqual(report["status"],"complete_broker_window")
        self.assertEqual(report["window_days"],7)
        for key in ("last_24h","last_7d"):
            wallet=report["wallet"][key]
            self.assertEqual(wallet["status"],"verified_posted_cashflow")
            self.assertEqual(wallet["posted_net_usd"],"14.20")
            self.assertEqual(wallet["gross_cashflow_usd"],"15.00")
            self.assertEqual(wallet["fees_usd"],"-1.00")
            self.assertEqual(wallet["funding_usd"],"0.20")
            self.assertEqual(wallet["excluded_external_transfers"],2)
            self.assertFalse(wallet["is_verified_trade_pnl"])
            self.assertFalse(wallet["is_strategy_attributed"])
        self.assertEqual(report["fire_trade_count_in_window"],3)
        self.assertEqual(report["broker_reconciled_closed_trades"],0)
        self.assertIsNone(report["verified_subset_net_usd"])
        self.assertIsNone(report["verified_subset_win_rate_pct"])
        self.assertFalse(report["is_account_net_realized_pnl"])
        self.assertTrue(any(r["reconciliation_status"]=="no_order"
                            for r in report["trade_rows"]))
        self.assertTrue(any(r["reconciliation_status"]=="unverified"
                            for r in report["trade_rows"]))
        self.assertTrue(any(r["reconciliation_status"]=="position_open_or_unresolved"
                            for r in report["trade_rows"]))
        self.assertTrue(all(method=="GET" for method,_ in broker.calls))
        self.assertNotIn("broker_order_id",json.dumps(report))

    def test_unknown_posting_category_never_becomes_zero_pnl(self):
        stamp=int(self.now.timestamp()*1000000)
        out=_cashflows([{"at_us":stamp,"asset":"USD","type":"mystery",
                         "amount":"9999"}],
            start_us=stamp-7*86400*1000000,end_us=stamp)
        self.assertEqual(out["last_7d"]["status"],"unclassified_postings")
        self.assertIsNone(out["last_7d"]["posted_net_usd"])

    def test_broker_history_failure_has_no_partial_financial_metrics(self):
        broker=CompleteReadOnlyBroker(self.now)
        broker.product_fills=Mock(side_effect=RuntimeError("unavailable"))
        with self.assertRaises(RuntimeError):
            collect_account_performance(broker,self.root,"BTCUSD",now=self.now)

    def test_wrong_account_scope_is_rejected(self):
        broker=CompleteReadOnlyBroker(self.now)
        with self.assertRaises(ValueError):
            collect_account_performance(broker,self.root,"XAUTUSD",now=self.now)
        broker.allow_orders=True
        with self.assertRaises(ValueError):
            collect_account_performance(broker,self.root,"BTCUSD",now=self.now)

    def test_get_only_performance_endpoint(self):
        class Stub:
            class Perf:
                def snapshot(self):
                    return {"mode":"read_only",
                        "source":"isolated_signed_broker_performance",
                        "accounts":{"BTC":{"status":"loading"},
                                    "GOLD":{"status":"loading"}}}
            pass
        # Bind the explicit stub without involving any real account credentials.
        Stub.isolated_accounts=type("A",(),{"performance":Stub.Perf()})()
        server=ThreadingHTTPServer(("127.0.0.1",0),create_handler(Stub()))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        Thread(target=server.serve_forever,daemon=True).start()
        base="http://127.0.0.1:"+str(server.server_address[1])
        with urlopen(base+"/api/isolated/performance") as response:
            report=json.load(response)
            self.assertEqual(report["mode"],"read_only")
            self.assertEqual(response.headers["Cache-Control"],"no-store")
        with urlopen(base+"/performance.js") as response:
            self.assertIn("last_24h",response.read().decode())
        with self.assertRaises(HTTPError) as blocked:
            urlopen(Request(base+"/api/isolated/performance",
                    data=b"{}",method="POST"))
        self.assertEqual(blocked.exception.code,405)


if __name__=="__main__":
    unittest.main()
