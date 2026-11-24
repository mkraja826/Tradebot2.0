import unittest
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.delta import DEMO_API
class Stub:
    base_url=DEMO_API
    allow_orders=False
    def __init__(self):self.calls=[]
    def _request(self,*a,**kw):self.calls.append(a);return {}
    def open_orders(self):self.calls.append("orders")
    def wallet_balances(self):self.calls.append("wallet")
class BoundaryTests(unittest.TestCase):
    def test_mutations_never_forwarded(self):
        c=Stub();r=AccountReader(c,"BTCUSD")
        for m in ("POST","PUT","PATCH","DELETE"):
            with self.assertRaises(ValueError):r._request(m,"/v2/users/trading_preferences",auth=True)
        self.assertEqual(c.calls,[])
    def test_client_scope_drift(self):
        for key,value in (("allow_orders",True),("base_url","fixture-other")):
            c=Stub();r=AccountReader(c,"BTCUSD");setattr(c,key,value)
            for call in (lambda:r._request("GET","/v2/users/trading_preferences",auth=True),r.open_orders,r.wallet_balances):
                with self.assertRaises(ValueError):call()
            self.assertEqual(c.calls,[])
    def test_unknown_market(self):
        with self.assertRaises(ValueError):AccountReader(Stub(),"UNKNOWN")
    def test_parent_inventory_refused(self):
        c=Stub();r=AccountReader(c)
        for call in (r.open_orders,r.wallet_balances):
            with self.assertRaises(ValueError):call()
        self.assertEqual(c.calls,[])
