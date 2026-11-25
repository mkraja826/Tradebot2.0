import unittest
from recover_trading.engine import Journal,OrderIntent
from recover_trading.order_poll import Schedule
from recover_trading.lifecycle import Lifecycle
from test_recover_lifecycle import Broker
class PollTests(unittest.TestCase):
    def test_backoff_and_fresh_priority(self):
        j=Journal(":memory:");self.addCleanup(j.close);s=Schedule(j.db)
        missing={"http_status":400,"exchange_code":"order_not_found"}
        for i in range(8):
            for t in (100,160,220):s.record(str(i),t,missing)
        rows=[(str(i),"unknown",{}) for i in range(8)]+[("new","unknown",{}),("pending","acknowledged",{})]
        picked,info=s.select(rows,300)
        self.assertEqual({r[0] for r in picked},{"new","pending"})
        self.assertEqual(info["historical_deferred"],8)
        picked,info=s.select(rows,3820)
        self.assertEqual(info["historical_selected"],3)
        self.assertEqual(info["due_remaining"],5)
        s.record("0",3820,missing)
        picked,_=s.select(rows,3821)
        self.assertNotIn("0",[r[0] for r in picked])
        self.assertIn("new",[r[0] for r in picked])
    def test_timeout_resets_missing_streak(self):
        j=Journal(":memory:");self.addCleanup(j.close);s=Schedule(j.db)
        for t in (100,160,220):s.record("a",t,{"http_status":400,"exchange_code":"order_not_found"})
        s.record("a",300,{"category":"timeout"})
        self.assertEqual(len(s.select([("a","unknown",{})],301)[0]),1)
    def test_lifecycle_recovers_exact_intent_once(self):
        j=Journal(":memory:");self.addCleanup(j.close);b=Broker();l=Lifecycle(b,j)
        j.begin("a","BTCUSD",OrderIntent(1,"buy",10));j.finish("a","unknown",{})
        calls=[]
        def lookup(i):
            calls.append(i);return {"id":42,"product_id":1,"client_order_id":i,"side":"buy","size":10,"unfilled_size":0,"state":"closed"}
        b.order=lookup
        r=l.refresh("BTCUSD")
        self.assertEqual(calls,["a"]);self.assertEqual(r["order_poll_schedule"]["checked"],1)
        self.assertEqual(j.db.execute("SELECT status FROM orders").fetchone()[0],"acknowledged")
        l.refresh("BTCUSD");self.assertEqual(calls,["a"])
