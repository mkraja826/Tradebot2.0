import unittest
from recover_trading.open_excursion import measure
from recover_trading.performance import stamp
class OpenExcursionTests(unittest.TestCase):
    def fixture(self):
        t=1795564800
        from datetime import datetime,timezone
        def iso(n):return datetime.fromtimestamp(t+n,timezone.utc).isoformat()
        f=[{"id":"a","product_id":84,"created_at":iso(0),"side":"buy","size":1,"price":100,"new_position":{"size":0}},{"id":"b","product_id":84,"created_at":iso(30),"side":"sell","size":3,"price":100,"new_position":{"size":-3}},{"id":"c","product_id":84,"created_at":iso(90),"side":"buy","size":1,"price":101,"new_position":{"size":-2}}]
        snap={"symbol":"BTCUSD","observed":t+210,"positions":[{"product_id":84,"size":-2,"entry_price":"100","mark_price":"99","created_at":iso(30)}],"active_orders":[],"active_orders_complete":True,"fill_window_complete":True}
        b={t+i*60:{"time":t+i*60,"open":100,"close":101,"high":h,"low":l} for i,h,l in ((0,999,1),(1,104,98),(2,103,95),(3,999,1))}
        return snap,t+210,f,b
    def test_open_with_reduction(self):
        s,n,f,b=self.fixture();r=measure(s,"BTCUSD",n,f,b)
        self.assertEqual(r["status"],"complete_interior_lower_bound")
        self.assertEqual(r["mfe_bps"],500)
        self.assertEqual(r["mae_bps"],400)
        self.assertEqual(r["current_mark_return_bps"],100)
        self.assertEqual(r["partial_reduction_fills"],1)
    def test_incomplete_and_identity(self):
        s,n,f,b=self.fixture()
        self.assertEqual(measure(s,"BTCUSD",n,f,{})["status"],"fills_only_lower_bound")
        self.assertEqual(measure(s,"BTCUSD",n,f[1:],b)["status"],"flat_anchor_unavailable")
        s["positions"][0]["size"]=-1
        self.assertEqual(measure(s,"BTCUSD",n,f,b)["status"],"position_size_unverified")
        s["fill_window_complete"]=False
        self.assertEqual(measure(s,"BTCUSD",n,f,b)["status"],"position_unverified")
