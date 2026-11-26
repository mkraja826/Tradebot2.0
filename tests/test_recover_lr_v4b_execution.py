import unittest
from recover_trading.engine import Journal
from recover_trading.execution import DemoExecutor
from recover_trading.lr_v4b_execution import bracket_proposal, submit
from test_recover_execution import Fake


class BookFake(Fake):
    def __init__(self):
        super().__init__()
        self.open_position=False
    def _request(self,method,path,**kw):
        r=super()._request(method,path,**kw)
        if path.startswith("/v2/products/"):
            r["tick_size"]="0.5"
        if path.startswith("/v2/tickers/"):
            r["quotes"]={"best_bid":"99.5","best_ask":"100"}
        if path=="/v2/positions/margined" and self.open_position:
            return [{"product_id":1,"size":"1"}]
        return r


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.broker=BookFake()
        self.journal=Journal(":memory:")
        self.addCleanup(self.journal.close)
        self.executor=DemoExecutor(self.broker,self.journal)
        self.signal={"version":"lr-v4b","symbol":"BTCUSD","side":"buy","signal_time":600,"burst_time":540,"initial_stop":95.2}
        self.sizing={"symbol":"BTCUSD","action":"trade","side":"buy","size":2,"leverage":20,"capital_allocation":1}
    def run_entry(self,**kw):
        return submit(self.signal,self.sizing,self.executor,clock=lambda:601,**kw)
    def order_count(self):
        return sum(m=="POST" and p=="/v2/orders" for m,p,k in self.broker.calls)
    def test_disabled_no_broker_calls(self):
        self.assertEqual(self.run_entry()["status"],"disabled")
        self.assertEqual(self.broker.calls,[])
    def test_bracket_and_duplicate(self):
        self.assertEqual(self.run_entry(enabled=True)["status"],"acknowledged")
        payload=next(k["payload"] for m,p,k in self.broker.calls if m=="POST" and p=="/v2/orders")
        self.assertEqual(float(payload["bracket_stop_loss_price"]),95)
        self.assertEqual(float(payload["bracket_take_profit_price"]),110)
        self.assertEqual(self.run_entry(enabled=True)["status"],"already_reserved")
        self.assertEqual(self.order_count(),1)
    def test_existing_position_not_merged(self):
        self.broker.open_position=True
        self.assertEqual(self.run_entry(enabled=True)["status"],"existing_position")
        self.assertEqual(self.order_count(),0)
    def test_ambiguous_submission_not_repeated(self):
        self.broker.timeout=True
        self.assertEqual(self.run_entry(enabled=True)["status"],"unknown")
        self.assertEqual(self.run_entry(enabled=True)["status"],"unresolved_submission")
        self.assertEqual(self.order_count(),1)
    def test_wrong_direction_and_expired_signal(self):
        self.sizing["side"]="sell"
        with self.assertRaises(ValueError):
            self.run_entry(enabled=True)
        self.assertEqual(submit(self.signal,self.sizing,self.executor,enabled=True,clock=lambda:660)["status"],"stale_signal")
        self.assertEqual(self.order_count(),0)
