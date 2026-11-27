"""Full controller lifecycle against an in-memory demo exchange fixture.

Real adapters, executor, journals and reconciliation; only broker I/O and
time are replaced. No credentials or network calls.
"""
import copy
import unittest
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from recover_trading.broker import DeltaDemo,BrokerError
from recover_trading.engine import Journal
from recover_trading.gold_v2_episode import EpisodeJournal
from recover_trading.gold_v2_controller import Controller,outstanding
from recover_trading.gold_v2_engine import Bar

B=3600000
def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()

class Exchange:
    def __init__(self):
        self.now=B+20;self.mark=100;self.qty=0;self.entry=100;self.created=None
        self.orders={};self.legs=[];self.fills=[];self.mutations=[];self.seq=100
        self.unknown_entry=False
    def tick(self,t,mark):self.now=t;self.mark=mark
    def product(self,s):
        assert s=="XAUTUSD"
        return {"id":42,"symbol":s,"contract_value":"1","contract_unit_currency":"XAUT",
                "settling_asset":{"symbol":"USD"},"quoting_asset":{"symbol":"USD"},"notional_type":"vanilla","tick_size":"0.1"}
    def wallet(self):return {"result":[{"asset_symbol":"USD","user_id":123,"balance":"100","available_balance":"100"}]}
    def positions(self,pid):
        assert pid==42
        return [{"product_id":42,"size":self.qty,"entry_price":self.entry,"mark_price":self.mark,
                 "created_at":self.created}] if self.qty else []
    def active(self,pid,after=None):
        assert pid==42
        return {"result":copy.deepcopy(self.legs),"meta":{}}
    def page(self,pid,after=None):
        assert pid==42
        return {"result":copy.deepcopy(self.fills),"meta":{}}
    def ticker(self,s):
        assert s=="XAUTUSD"
        return {"symbol":s,"product_id":42,"timestamp":self.now*1000000,"mark_price":str(self.mark),
                "quotes":{"best_bid":str(self.mark),"best_ask":str(self.mark)}}
    def lookup(self,cid):
        if cid not in self.orders:raise BrokerError(exchange_code="order_not_found")
        return copy.deepcopy(self.orders[cid])
    def fill(self,oid,side,size,price):
        self.qty+=size if side=="buy" else -size
        self.fills.append({"id":len(self.fills)+1,"order_id":oid,"product_id":42,"side":side,
            "size":size,"price":price,"created_at":iso(self.now),"meta_data":{"new_position":{"size":self.qty}}})
    def open(self,intent,cid):
        assert not self.qty and intent.product_id==42 and intent.leverage==20
        self.mutations.append("entry");self.seq+=3;self.now+=1
        self.created=iso(self.now);self.entry=self.mark
        r={"id":self.seq,"client_order_id":cid,"product_id":42,"user_id":123,"side":intent.side,
           "size":intent.size,"unfilled_size":0,"state":"closed","reduce_only":False,
           "average_fill_price":self.entry,"bracket_stop_loss_price":intent.stop_loss,
           "bracket_take_profit_price":intent.take_profit}
        self.orders[cid]=r;self.fill(r["id"],intent.side,intent.size,self.entry)
        self.legs=[{"id":self.seq+i,"product_id":42,"user_id":123,"side":"sell" if self.qty>0 else "buy",
                   "size":abs(self.qty),"unfilled_size":abs(self.qty),"state":"pending","reduce_only":True,
                   "bracket_order":True,"stop_trigger_method":"mark_price","stop_order_type":kind,"stop_price":price}
                   for i,(kind,price) in enumerate((("stop_loss_order",intent.stop_loss),("take_profit_order",intent.take_profit)),1)]
        if self.unknown_entry:raise BrokerError(category="transport")
        return copy.deepcopy(r)
    def reduce(self,intent,cid):
        assert intent.reduce_only and intent.size<=abs(self.qty)
        self.mutations.append("reduce");self.seq+=10;self.now+=1
        r={"id":self.seq,"client_order_id":cid,"product_id":42,"side":intent.side,
           "size":intent.size,"unfilled_size":0,"state":"closed","reduce_only":True,"average_fill_price":self.mark}
        self.orders[cid]=r;self.fill(r["id"],intent.side,intent.size,self.mark)
        for leg in self.legs:leg.update(size=abs(self.qty),unfilled_size=abs(self.qty))
        if not self.qty:self.legs=[]
        return copy.deepcopy(r)
    def request(self,method,path,**kw):
        if method=="PUT" and path=="/v2/orders":
            self.mutations.append("amend")
            p=kw["payload"];leg=next(x for x in self.legs if x["id"]==p["id"])
            leg["stop_price"]=p["stop_price"];return copy.deepcopy(leg)
        if method=="GET" and path.startswith("/v2/orders/"):
            oid=int(path.rsplit("/",1)[-1]);return copy.deepcopy(next(x for x in self.orders.values() if x["id"]==oid))
        raise AssertionError("unexpected broker request")
    def trigger(self,kind):
        leg=next(x for x in self.legs if x["stop_order_type"]==kind)
        r=dict(leg,state="closed",unfilled_size=0)
        self.orders["protective-"+str(r["id"])]=r
        self.fill(r["id"],r["side"],r["size"],self.mark);self.legs=[]
    def attach(self,stack,broker):
        for name,fn in {"wallet":self.wallet,"product":self.product,"positions":self.positions,
                        "margined_positions":self.positions,"active_orders_page":self.active,"fills_page":self.page,
                        "ticker":self.ticker,"order":self.lookup,"submit_bracket":self.open,"submit":self.reduce,
                        "_request":self.request,"set_order_leverage":lambda pid:{"leverage":20}}.items():
            stack.enter_context(patch.object(broker,name,side_effect=fn))
        stack.enter_context(patch("time.time",side_effect=lambda:self.now))
        stack.enter_context(patch("time.time_ns",side_effect=lambda:self.now*1000000000))

def report(t):
    return {"symbol":"XAUTUSD","status":"observed","as_of":t//300*300,"decision_as_of":t,
            "features":{300:{"atr":2,"ema":[100,100,100,100]}},
            "candidates":[{"family":"trend_pullback","direction":"LONG","atr":2,
                           "stop_distance_atr_hypothesis":1.5,"target_distance_atr_hypothesis":3}]}

class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(TemporaryDirectory()))
        self.exchange=Exchange();self.broker=DeltaDemo()
        self.exchange.attach(self.stack,self.broker)
        self.reopen()
    def reopen(self):
        if hasattr(self,"orders"):self.orders.close();self.episodes.close()
        self.orders=Journal(self.root/"orders.sqlite")
        self.episodes=EpisodeJournal(self.root/"episodes.sqlite")
        self.controller=Controller(self.broker,self.orders,self.episodes,expected_account="123",
                                   allocation_fraction=.1,enabled=True,clock=lambda:self.exchange.now)
    def tearDown(self):self.orders.close();self.episodes.close()
    def cycle(self,bars=()):return self.controller.cycle(report(self.exchange.now),bars)
    def test_entry_trail_partial_restart_protective_exit_next_entry(self):
        e=self.exchange
        x=self.cycle()
        self.assertEqual(x["execution_status"],"acknowledged")
        self.assertEqual(x["post_entry_observation"],"owned_open")
        self.assertEqual(e.qty,2)
        e.tick(B+620,102)
        bars=[Bar(B+600,100,102.5,99.5,102,1)]
        x=self.cycle(bars)
        self.assertEqual(x["management_status"],"verified",x)
        self.assertEqual(e.mutations,["entry","amend"])
        e.tick(B+920,103.5)
        bars.append(Bar(B+900,102,104,101.5,103.5,1))
        x=self.cycle(bars)
        self.assertEqual(x["management_status"],"verified",x)
        self.assertEqual(e.qty,1)
        self.reopen()
        e.tick(B+1220,104)
        bars.append(Bar(B+1200,103.5,104.5,103,104,1))
        self.cycle(bars)
        self.assertEqual(e.qty,1)
        e.tick(B+1240,106);e.trigger("take_profit_order")
        self.assertEqual(self.cycle(bars)["status"],"closed")
        self.assertFalse(outstanding(self.episodes))
        e.tick(B+1520,100)
        self.assertEqual(self.cycle()["execution_status"],"acknowledged")
        self.assertEqual(e.mutations.count("entry"),2)
    def test_lost_acknowledgment_recovered_without_resubmission(self):
        e=self.exchange;e.unknown_entry=True
        self.assertEqual(self.cycle()["execution_status"],"unknown")
        self.assertEqual(e.mutations,["entry"])
        self.reopen();e.tick(B+40,100)
        self.cycle()
        self.assertFalse(self.orders.unresolved())
        self.assertEqual(e.mutations,["entry"])
