"""Offline integration: scanner reports -> proposal -> demo HTTP adapter -> journals -> dashboard."""
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from recover_trading.dashboard import handler, report as dashboard_report
from recover_trading.service import MarketService
from test_recover_service import Provider, scan
from test_recover_execution import Fake

class Exchange(Fake):
    def __init__(self, symbol):
        super().__init__()
        self.symbol = symbol
        self.pid = 1 if symbol == "BTCUSD" else 2
        self.entry = None
    def _request(self, method, path, **kwargs):
        if method == "POST" and path == "/v2/orders":
            self.entry = kwargs["payload"]
            # Simulate an accepted order whose response was lost.
            self.calls.append((method,path,kwargs))
            raise TimeoutError()
        if path.startswith("/v2/orders/client_order_id/") and self.entry:
            self.calls.append((method,path,kwargs))
            return {"id":42,"product_id":self.pid,
                    "client_order_id":self.entry["client_order_id"],"side":self.entry["side"],
                    "size":90,"unfilled_size":0,"state":"closed","average_fill_price":"100"}
        if method == "GET" and path == "/v2/positions/margined" and self.entry:
            return [{"product_id":self.pid,"size":-90,"margin":"45","entry_price":"100"}]
        if method == "GET" and path == "/v2/orders" and self.entry:
            return {"result":[{"product_id":self.pid,"side":"buy","state":"pending",
                               "reduce_only":True,"stop_price":p,"stop_order_type":t}
                              for p,t in [("105","stop_loss_order"),("95","take_profit_order")]]}
        if path == "/v2/fills" and self.entry:
            return {"result":[{"id":"f1","product_id":self.pid,"order_id":42,
                               "price":"100","size":90,"side":"sell"}]}
        return super()._request(method,path,**kwargs)

class EndToEndTests(unittest.TestCase):
    def test_both_markets_restart_and_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            for symbol in ("BTCUSD","XAUTUSD"):
                broker, provider, events = Exchange(symbol), Provider(), []
                for _ in range(3):
                    service=MarketService(symbol,d,model="fixture",broker=broker,
                                          provider=provider,scan=scan,output=events.append)
                    service.run(threading.Event(),1,once=True)
                self.assertEqual(events[0]["execution_status"],"unknown")
                self.assertEqual(events[1]["status"],"already_evaluated")
                self.assertEqual(provider.calls,1)
                self.assertEqual(sum(p.startswith("/v2/orders/client_order_id/") for m,p,k in broker.calls),1)
                self.assertEqual(sum(m=="POST" and p=="/v2/orders" for m,p,k in broker.calls),1)
                r=dashboard_report(d,symbol)
                self.assertEqual(r["orders"][0]["status"],"acknowledged")
                self.assertEqual(r["orders"][0]["exchange"]["status"],"filled")
                self.assertEqual(r["orders"][0]["intent"]["leverage"],20)
                self.assertEqual(r["snapshot"]["bracket_evidence"],"both_legs_observed")
                self.assertEqual(r["snapshot"]["positions"][0]["margin"],"45")
                self.assertEqual(len(r["fills"]),1)
                self.assertEqual(r["decisions"][0]["result"]["capital_allocation"],45)
                self.assertEqual(r["heartbeat"]["symbol"],symbol)
                self.assertIsNone(r["win_rate"])
    def test_dashboard_http_contract(self):
        with tempfile.TemporaryDirectory() as d:
            with ThreadingHTTPServer(("127.0.0.1",0),handler(d)) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                try:
                    c=HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                    try:
                        c.request("GET","/api/overview")
                        r=c.getresponse()
                        self.assertEqual(r.status,200)
                        self.assertEqual(r.getheader("Cache-Control"),"no-store")
                        self.assertEqual([m["symbol"] for m in json.loads(r.read())["markets"]],
                                         ["BTCUSD","XAUTUSD"])
                        c.request("GET","/");r=c.getresponse()
                        self.assertEqual(r.status,200)
                        self.assertIn(b"Trading overview",r.read())
                        c.request("GET","/api/overview",headers={"Host":"external.invalid"})
                        r=c.getresponse();self.assertEqual(r.status,403);r.read()
                        c.request("POST","/api/overview")
                        r=c.getresponse();self.assertEqual(r.status,501);r.read()
                    finally:
                        c.close()
                finally:
                    server.shutdown()
                    thread.join()
