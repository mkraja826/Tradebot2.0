import json,time,unittest
from recover_trading.engine import Journal
from recover_trading.broker import DeltaDemo
from recover_trading.management_shadow import ManagementShadow,context_for
from recover_trading.management_executor import ManagementExecutor
class Fake(DeltaDemo):
    def __init__(self):
        self.q=-24;self.sl="105";self.tp="95";self.calls=0;self.unknown=False;self.order_row=None
    def product(self,s):return {"id":84,"symbol":s,"tick_size":"0.1"}
    def margined_positions(self,p):return [{"product_id":84,"size":self.q,"entry_price":"100","mark_price":"101","created_at":"2026-11-25T08:00:00Z"}] if self.q else []
    def active_orders_page(self,p,after=None):
        return {"result":[{"id":i,"product_id":84,"side":"buy","state":"pending","size":abs(self.q),"unfilled_size":abs(self.q),"stop_order_type":k,"stop_price":v,"reduce_only":True,"bracket_order":True,"stop_trigger_method":"mark_price"} for i,k,v in ((1,"stop_loss_order",self.sl),(2,"take_profit_order",self.tp))] if self.q and self.sl else []}
    def ticker(self,s):return {"symbol":s,"product_id":84,"timestamp":time.time_ns()//1000,"mark_price":"101"}
    def _request(self,method,path,**kw):
        self.calls+=1
        if self.unknown:raise TimeoutError()
        if method=="PUT":
            self.sl=kw["payload"]["stop_price"];return {"id":1,"stop_price":self.sl}
        self.sl=kw["payload"]["stop_loss_order"]["stop_price"];self.tp=kw["payload"]["take_profit_order"]["stop_price"];return {"success":True}
    def submit(self,intent,cid):
        self.calls+=1
        if self.unknown:raise TimeoutError()
        assert intent.reduce_only and intent.side=="buy"
        self.q+=intent.size
        self.order_row={"id":42,"client_order_id":cid,"product_id":84,"side":"buy","size":intent.size,"unfilled_size":0,"state":"closed","reduce_only":True}
        return self.order_row
    def order(self,cid):return self.order_row
    def fills_page(self,p,after=None):
        return {"result":[{"id":"f","product_id":84,"order_id":42,"side":"buy","size":self.order_row["size"]}] if self.order_row else []}
class ManagementExecutorTests(unittest.TestCase):
    def setUp(self):
        self.b=Fake();self.j=Journal(":memory:");self.addCleanup(self.j.close)
        ManagementShadow(self.j.db);self.e=ManagementExecutor(self.b,self.j)
    def proposal(self,action,**kw):
        now=int(time.time());s=self.e.reader.observe("BTCUSD",84)
        c=context_for({"symbol":"BTCUSD","as_of":now,"signals":[],"market_context":{}},s,self.b.product("BTCUSD"),now)
        i=str(time.time_ns())
        with self.j.db:self.j.db.execute("INSERT INTO management_shadow VALUES (?,?,?,?,?,'proposed',?,?)",(i,"BTCUSD",int(i),now,"mock",json.dumps(c),json.dumps({"proposal":{"symbol":"BTCUSD","action":action,"reason":"fixture",**kw}})))
        return i
    def test_opt_in_and_reduce(self):
        i=self.proposal("reduce",contracts=1)
        self.assertEqual(self.e.execute("BTCUSD",i)["status"],"execution_disabled")
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"verified")
        self.assertEqual(self.b.q,-23)
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"already_recorded")
        self.assertEqual(self.b.calls,1)
    def test_stop_only(self):
        i=self.proposal("update_bracket",stop_loss=104.9,take_profit=95)
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"verified")
        self.assertEqual(self.b.sl,"104.9")
        i=self.proposal("update_bracket",stop_loss=104.9,take_profit=94)
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"take_profit_amendment_not_verified")
    def test_repair(self):
        self.b.sl=None
        i=self.proposal("repair_bracket",stop_loss=105,take_profit=95)
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"verified")
    def test_unknown_no_replay(self):
        self.b.unknown=True;i=self.proposal("reduce",contracts=1)
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"outcome_unverified")
        i=self.proposal("reduce",contracts=1)
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"previous_management_outcome_unverified")
        self.assertEqual(self.b.calls,1)
    def test_full_close(self):
        i=self.proposal("close")
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"verified")
        self.assertEqual(self.b.q,0)
    def test_changed_legs(self):
        i=self.proposal("update_bracket",stop_loss=104.9,take_profit=95)
        self.b.sl="106"
        self.assertEqual(self.e.execute("BTCUSD",i,enabled=True)["status"],"position_or_order_identity_changed")
        self.assertEqual(self.b.calls,0)
