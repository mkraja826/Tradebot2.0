import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.m34_boundary_audit_v3 import inventory
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from test_signed_account_context_v3 import Broker

class BoundaryAuditTests(unittest.TestCase):
    def test_inventory_explicit_and_dynamic(self):
        with TemporaryDirectory() as d:
            Path(d,"fixture.py").write_text('x._request("GET", p)\nx._request("POST", p)\nx._request(method=m,path=p)\nx.cancel_product_orders(1)\n')
            self.assertEqual([r["call"] for r in inventory(d)],["request_POST","request_dynamic","cancel_product_orders"])
    def test_readonly_denies_mutations_before_forwarding(self):
        for s in ("BTCUSD","XAUTUSD",None):
            b=Broker();r=AccountReader(b,s)
            for m in ("POST","PUT","PATCH","DELETE","get"):
                with self.assertRaises(ValueError):r._request(m,"/v2/users/trading_preferences",True)
            self.assertEqual(b.calls,[])
    def test_capability_drift(self):
        b=Broker();r=AccountReader(b,"BTCUSD")
        b.allow_orders=True
        for f in (r.open_orders,r.wallet_balances,lambda:r._request("GET","/v2/users/trading_preferences",True)):
            with self.assertRaises(ValueError):f()
        self.assertEqual(b.calls,[])
