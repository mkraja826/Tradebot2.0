import json,time,unittest
from recover_trading.broker import DeltaDemo
from recover_trading.engine import Journal
from recover_trading.bracket_repair import BracketRepair,entry_lineage

def position():return {"product_id":84,"size":-25,"entry_price":"100","created_at":"2026-11-25T08:00:01Z"}
def fills():
    return [{"id":"old","order_id":"old-order","product_id":84,"side":"buy","size":"25","price":"99","created_at":"2026-11-25T08:00:00Z","meta_data":{"new_position":{"size":0}}},
            {"id":"new","order_id":"42","product_id":84,"side":"sell","size":"25","price":"100","created_at":"2026-11-25T08:00:01Z","meta_data":{"new_position":{"size":-25}}}]
class Fake(DeltaDemo):
    def __init__(self):
        self.orders=[];self.posts=0;self.mark=100;self.timeout=False
    def product(self,s):return {"symbol":s,"id":84,"tick_size":"0.1"}
    def margined_positions(self,p):return [position()]
    def active_orders_page(self,p,after=None):return {"result":self.orders}
    def fills_page(self,p,after=None):return {"result":fills()}
    def ticker(self,s):return {"symbol":s,"product_id":84,"timestamp":time.time_ns()//1000,"mark_price":str(self.mark)}
    def _request(self,method,path,**kw):
        assert method=="POST" and path=="/v2/orders/bracket"
        self.posts+=1
        if self.timeout:raise TimeoutError()
        p=kw["payload"]
        self.orders=[{"id":i,"product_id":84,"state":"pending","side":"buy","unfilled_size":25,"reduce_only":True,"bracket_order":True,"stop_order_type":k+"_order","stop_price":p[k+"_order"]["stop_price"],"stop_trigger_method":"mark_price"} for i,k in enumerate(("stop_loss","take_profit"),1)]
        return {"success":True}
class BracketRepairTests(unittest.TestCase):
    def setUp(self):
        self.b=Fake();self.j=Journal(":memory:");self.addCleanup(self.j.close)
        self.repair=BracketRepair(self.b,self.j)
        self.intent={"product_id":84,"side":"sell","size":25,"stop_loss":105,"take_profit":95}
        self.receipt={"id":42,"client_order_id":"c","product_id":84,"state":"closed","side":"sell","size":25,"unfilled_size":0,"reduce_only":False,"bracket_stop_loss_price":"105","bracket_take_profit_price":"95"}
        with self.j.db:self.j.db.execute("INSERT INTO orders VALUES (?,?,?,?,?)",("c","BTCUSD",json.dumps(self.intent),"acknowledged",json.dumps(self.receipt)))
    def cycle(self):return self.repair.cycle("BTCUSD",self.repair.observe("BTCUSD",84))
    def test_verified_restore_and_no_duplicate(self):
        self.assertEqual(self.cycle()["status"],"matching_triggers_observed")
        self.assertEqual(self.cycle()["status"],"existing_bracket_observed")
        self.assertEqual(self.b.posts,1)
    def test_unknown_not_retried(self):
        self.b.timeout=True
        self.assertTrue(self.cycle()["attempted"])
        self.assertEqual(self.cycle()["status"],"prior_attempt_no_retry")
        self.assertEqual(self.b.posts,1)
    def test_crossed_mark_requires_ai_prices(self):
        self.b.mark=94
        self.assertEqual(self.cycle()["status"],"fresh_ai_prices_required")
        self.assertEqual(self.b.posts,0)
    def test_no_matching_lineage(self):
        self.receipt["client_order_id"]="wrong"
        with self.j.db:self.j.db.execute("UPDATE orders SET detail=?",(json.dumps(self.receipt),))
        self.assertEqual(self.cycle()["status"],"entry_lineage_unverified")
        self.assertEqual(self.b.posts,0)
