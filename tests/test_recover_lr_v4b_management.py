import json
import time
import unittest
from datetime import datetime, timezone
from recover_trading.engine import Journal
from recover_trading.management_executor import ManagementExecutor
from recover_trading.lr_v4b_attribution import Attribution
from recover_trading.lr_v4b_management import LRManager
from test_recover_management_executor import Fake


class LRBroker(Fake):
    def __init__(self,now):
        super().__init__()
        self.cid=None
        self.entry_time=now-125
        self.tp="90"
    def order(self,cid):
        if cid==self.cid:
            return {"id":9,"client_order_id":cid,"product_id":84,"side":"sell","size":24,
                    "unfilled_size":0,"state":"closed","reduce_only":False,
                    "bracket_stop_loss_price":"105","bracket_take_profit_price":"95"}
        return super().order(cid)
    def fills_page(self,p,after=None):
        def dt(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
        rows=[{"id":"a","order_id":8,"product_id":84,"side":"buy","size":1,"price":"100",
               "created_at":dt(self.entry_time-60),"meta_data":{"new_position":{"size":0}}},
              {"id":"b","order_id":9,"product_id":84,"side":"sell","size":24,"price":"100",
               "created_at":dt(self.entry_time),"meta_data":{"new_position":{"size":-24}}}]
        if self.order_row:
            rows.append({"id":"c","product_id":84,"order_id":42,"side":"buy",
                         "size":self.order_row["size"],"created_at":dt(time.time())})
        return {"result":rows}


class LRManagementTests(unittest.TestCase):
    def setUp(self):
        self.now=int(time.time())
        self.b=LRBroker(self.now)
        self.j=Journal(":memory:")
        self.addCleanup(self.j.close)
        self.m=LRManager(ManagementExecutor(self.b,self.j))
        t=self.now//60*60
        a=Attribution(self.j.db)
        self.b.cid=a.reserve({"version":"lr-v4b","symbol":"BTCUSD","side":"sell",
             "signal_time":t,"burst_time":t,"initial_stop":105},self.now)["client_id"]
        self.j.db.execute("INSERT INTO orders VALUES(?,?,?,?,?)",(self.b.cid,"BTCUSD",
            json.dumps({"side":"sell","size":24,"product_id":84,"stop_loss":105,"take_profit":95}),
            "acknowledged",json.dumps({"id":9,"client_order_id":self.b.cid})))
        self.j.db.commit()
        self.report={"symbol":"BTCUSD","as_of":self.now,"signals":[],"market_context":{}}
    def run_m(self,enabled=True):
        start=(self.b.entry_time+59)//60*60
        rows=[{"time":t,"open":103,"high":104,"low":97,"close":103}
              for t in range(start,self.now//60*60,60)]
        return self.m.run(self.report,rows,enabled=enabled,now=self.now)
    def test_disabled(self):
        self.assertEqual(self.run_m(False)["status"],"disabled")
        self.assertEqual(self.b.calls,0)
    def test_unowned(self):
        self.j.db.execute("DELETE FROM lr_v4b_entries")
        self.assertEqual(self.run_m()["status"],"ownership_unverified")
        self.assertEqual(self.b.calls,0)
    def test_stop_only(self):
        self.assertEqual(self.run_m()["status"],"verified")
        self.assertEqual(self.b.sl,"103.0")
        self.assertEqual(self.b.tp,"90")
        self.assertEqual(self.b.calls,1)
    def test_rebase_target_only(self):
        self.b.tp="95"
        self.assertEqual(self.run_m()["status"],"verified")
        self.assertEqual(float(self.b.tp),90)
        self.assertEqual(self.b.sl,"105")
    def test_timeout_close(self):
        self.b.entry_time=self.now-3601
        self.assertEqual(self.run_m()["status"],"verified")
        self.assertEqual(self.b.q,0)
    def test_timeout_unknown_no_replay(self):
        self.b.entry_time=self.now-3601
        self.b.unknown=True
        self.assertEqual(self.run_m()["status"],"outcome_unverified")
        self.assertEqual(self.run_m()["status"],"already_reserved")
        self.assertEqual(self.b.calls,1)
