import unittest
from recover_trading.broker import DeltaDemo
from recover_trading.engine import Journal
from recover_trading.execution import DemoExecutor, account_context
from recover_trading.decision import validate

class Fake(DeltaDemo):
    def __init__(self):
        self.calls = []
        self.leverage = 20
        self.timeout = False
    def _request(self, method, path, **kwargs):
        self.calls.append((method,path,kwargs))
        if path.startswith("/v2/products/") and method == "GET":
            return {"id": 1 if path.endswith("BTCUSD") else 2,
                    "symbol": path.rsplit("/",1)[1], "contract_value": "0.001"}
        if path == "/v2/wallet/balances":
            return {"result":[{"asset_symbol":"USD","balance":"1000","available_balance":"900","user_id":123}]}
        if path == "/v2/positions":
            return []
        if path.endswith("/leverage"):
            return {"leverage":self.leverage}
        if method == "GET" and path in ("/v2/orders", "/v2/fills"):
            return {"result": []}
        if path == "/v2/positions/margined":
            return []
        if method == "POST" and path == "/v2/orders":
            if self.timeout:
                raise TimeoutError()
            return {"id": 42}
        if path.startswith("/v2/orders/client_order_id/"):
            return {"id": 42}
        raise AssertionError(path)

def proposal(symbol="BTCUSD",side="buy"):
    return {"symbol":symbol,"status":"proposed","decision_id":symbol,
            "proposal":{"symbol":symbol,"action":"trade","reason":"fixture",
                        "side":side,"size":90,"leverage":20,"capital_allocation":45,
                        "entry_reference":100,"stop_loss":95 if side=="buy" else 105,
                        "take_profit":105 if side=="buy" else 95}}

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.broker=Fake()
        self.journal=Journal(":memory:")
        self.addCleanup(self.journal.close)
        self.executor=DemoExecutor(self.broker,self.journal)
    def test_both_markets_and_no_duplicate(self):
        for symbol,side in [("BTCUSD","buy"),("XAUTUSD","sell")]:
            a=account_context(self.broker,symbol)
            self.assertNotIn("user_id",a["wallets"][0])
            r=proposal(symbol,side)
            self.assertEqual(self.executor.execute(r,account=a)["status"],"acknowledged")
            self.assertEqual(self.executor.execute(r,account=a)["status"],"already_recorded")
        orders=[k["payload"] for m,p,k in self.broker.calls if p=="/v2/orders"]
        self.assertEqual(len(orders),2)
        self.assertEqual([o["size"] for o in orders],[90,90])
        self.assertEqual([o["bracket_stop_loss_price"] for o in orders],["95","105"])
        self.assertEqual([o["bracket_take_profit_price"] for o in orders],["105","95"])
        self.assertEqual([k["payload"]["leverage"] for m,p,k in self.broker.calls if p.endswith("/leverage")],[20,20])
    def test_exchange_leverage_failure(self):
        self.broker.leverage=10
        self.assertEqual(self.executor.execute(proposal(),account=account_context(self.broker,"BTCUSD"))["status"],"preparation_failed")
        self.assertFalse(any(p=="/v2/orders" for m,p,k in self.broker.calls))
    def test_timeout_reconcile(self):
        self.broker.timeout=True
        a=account_context(self.broker,"BTCUSD")
        self.assertEqual(self.executor.execute(proposal(),account=a)["status"],"unknown")
        self.executor.reconcile()
        self.assertEqual(self.journal.unresolved(),[])
        self.assertEqual(self.executor.execute(proposal(),account=a)["status"],"already_recorded")
        self.assertEqual(sum(p=="/v2/orders" for m,p,k in self.broker.calls),1)
    def test_capital_and_leverage_required(self):
        p=proposal()["proposal"]
        p["leverage"]=19
        with self.assertRaises(ValueError):
            validate(p,"BTCUSD",require_capital=True)
        p["leverage"]=20
        del p["capital_allocation"]
        with self.assertRaises(ValueError):
            validate(p,"BTCUSD",require_capital=True)
