"""No fabricated P&L: signed broker cashflow and strict closed-FIRE evidence."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    _cashflows, _cashflow_buckets, _trade_distribution,
    collect_account_performance, IsolatedPerformanceDashboard)
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
            self.assertEqual(Decimal(wallet["posted_net_usd"]),Decimal("14.20"))
            self.assertEqual(Decimal(wallet["gross_cashflow_usd"]),Decimal("15.00"))
            self.assertEqual(Decimal(wallet["fees_usd"]),Decimal("-1.00"))
            self.assertEqual(Decimal(wallet["funding_usd"]),Decimal("0.20"))
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

    def test_signed_cashflow_chart_buckets_equal_full_window(self):
        report=collect_account_performance(
            CompleteReadOnlyBroker(self.now),self.root,"BTCUSD",now=self.now)
        series=report["cashflow_series"]
        self.assertEqual(series["source"],"complete_signed_wallet_postings")
        self.assertFalse(series["is_verified_trade_pnl"])
        self.assertFalse(series["is_strategy_attributed"])
        self.assertEqual(len(series["last_24h"]),12)
        self.assertEqual(len(series["last_7d"]),7)
        for key in ("last_24h","last_7d"):
            parts=series[key]
            self.assertEqual(
                sum((Decimal(p["posted_net_usd"]) for p in parts),Decimal(0)),
                Decimal("14.20"))
            self.assertEqual(sum(p["included_postings"] for p in parts),3)
            self.assertEqual(sum(p["excluded_external_transfers"]
                                 for p in parts),2)
            self.assertTrue(all(not p["is_strategy_attributed"] for p in parts))
            self.assertTrue(parts[-1]["partial"])
        d=report["trade_distribution"]
        self.assertEqual(d["total"],3)
        self.assertEqual(d["counts"]["no_order"],1)
        self.assertEqual(d["counts"]["open_or_unresolved"],1)
        self.assertEqual(d["counts"]["unverified"],1)
        self.assertEqual(sum(d["counts"].values()),3)
        self.assertFalse(d["is_win_rate"])

    def test_unclassified_bucket_suppresses_amount_and_retains_other_buckets(self):
        end=int(self.now.timestamp()*1_000_000)
        out=_cashflow_buckets([
            {"at_us":end-3600*1_000_000,"asset":"USD",
             "type":"mystery","amount":"5000"},
            {"at_us":end-8*3600*1_000_000,"asset":"USD",
             "type":"cashflow","amount":"-2.5"}],
            start_us=end-7*86400*1_000_000,end_us=end)
        hourly=out["last_24h"]
        self.assertEqual(hourly[-1]["status"],"unclassified_postings")
        self.assertIsNone(hourly[-1]["posted_net_usd"])
        self.assertEqual(hourly[-4]["status"],"verified_posted_cashflow")
        self.assertEqual(Decimal(hourly[-4]["posted_net_usd"]),Decimal("-2.5"))
        self.assertEqual(out["last_7d"][-1]["status"],"unclassified_postings")

    def test_trade_distribution_counts_verified_and_unverified_separately(self):
        rows=[
            {"is_net_realized_pnl":True,"net_realized_pnl_usd":"2"},
            {"is_net_realized_pnl":True,"net_realized_pnl_usd":"-1"},
            {"is_net_realized_pnl":True,"net_realized_pnl_usd":"0"},
            {"is_net_realized_pnl":False,"reconciliation_status":"no_order"},
            {"is_net_realized_pnl":False,
             "reconciliation_status":"position_open_or_unresolved"},
            {"is_net_realized_pnl":False,"reconciliation_status":"unverified"},
        ]
        d=_trade_distribution(rows)
        self.assertEqual(d["total"],6)
        self.assertTrue(all(v==1 for v in d["counts"].values()))
        self.assertEqual(d["coverage"],"complete_7d_receipts")
        self.assertEqual(_trade_distribution(rows,truncated=True)["coverage"],
                         "partial_bounded_receipts")

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
