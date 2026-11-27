import unittest
from datetime import datetime,timezone
from recover_trading.gold_v2_resize import addition_preview,verify_addition

NOW=3600020
PRODUCT={"symbol":"XAUTUSD","id":42}
def snapshot(q=4,avg=100,stop=100,target=106,mark=102,at=NOW):
    return {"symbol":"XAUTUSD","observed":at,"positions":[{"product_id":42,"size":q,
        "entry_price":avg,"mark_price":mark,"created_at":"fixture"}],
        "active_orders_complete":True,"active_orders":[
        {"id":i,"product_id":42,"side":"sell" if q>0 else "buy","state":"open",
         "stop_order_type":kind,"stop_price":price,"unfilled_size":abs(q),
         "reduce_only":True,"bracket_order":True,"stop_trigger_method":"mark_price"}
        for i,(kind,price) in enumerate((("stop_loss_order",stop),("take_profit_order",target)),1)]}
def preview(s=None,**kw):
    args=dict(now=NOW,initial_qty=4,initial_entry=100,initial_stop=98,atr=1,
              completed_close=102,quote={"status":"fresh_book","timestamp_us":NOW*1000000,
                                         "best_bid":101.9,"best_ask":102},
              adds=0,previous_reduction=False,cost_bps=0)
    args.update(kw)
    return addition_preview(snapshot() if s is None else s,PRODUCT,**args)
def evidence():
    before=snapshot(at=NOW-10)
    after=snapshot(q=8,avg=101)
    order={"id":9,"client_order_id":"fixture","product_id":42,"side":"buy",
           "reduce_only":False,"state":"closed","size":4,"unfilled_size":0,"average_fill_price":102}
    fills=[{"id":1,"order_id":9,"product_id":42,"side":"buy","size":4,"price":102,
            "created_at":datetime.fromtimestamp(NOW-5,timezone.utc).isoformat(),"new_position":{"size":8}}]
    return before,after,order,fills
def verify(b,a,o,f,complete=True):
    return verify_addition(b,a,PRODUCT,o,f,now=NOW,expected_client_id="fixture",
                           requested_contracts=4,complete=complete)

class ResizeTests(unittest.TestCase):
    def test_preview(self):
        x=preview()
        self.assertEqual((x["status"],x["additional_contracts"],x["expected_signed_size"]),("addition_preview",4,8))
        self.assertEqual(x["expected_weighted_entry"],"101")
        self.assertFalse(x["dispatch_supported"])
    def test_risk_reject(self):
        self.assertEqual(preview(snapshot(stop=98))["status"],"modeled_stop_budget_exceeded")
    def test_reduction_prevents_add(self):
        self.assertEqual(preview(previous_reduction=True)["status"],"no_addition_hypothesis")
    def test_short(self):
        x=preview(snapshot(q=-4,stop=100,target=94,mark=98),initial_stop=102,
                  completed_close=98,quote={"status":"fresh_book","timestamp_us":NOW*1000000,
                                             "best_bid":98,"best_ask":98.1})
        self.assertEqual(x["expected_signed_size"],-8)
        self.assertEqual(x["expected_weighted_entry"],"99")
    def test_stale_quote(self):
        self.assertEqual(preview(quote={"status":"fresh_book","timestamp_us":0})["status"],"quote_stale")
    def test_reconcile(self):
        x=verify(*evidence())
        self.assertEqual(x["status"],"addition_observed")
        self.assertFalse(x["continuous_coverage_verified"])
    def test_partial_fill(self):
        b,a,o,f=evidence()
        a=snapshot(q=6,avg="100.6666666666666666666666667")
        o.update(state="cancelled",unfilled_size=2)
        f[0].update(size=2,new_position={"size":6})
        self.assertEqual(verify(b,a,o,f)["status"],"addition_observed")
    def test_bracket_quantity_mismatch(self):
        b,a,o,f=evidence();a["active_orders"][0]["unfilled_size"]=4
        self.assertEqual(verify(b,a,o,f)["status"],"bracket_coverage_unverified")
    def test_unattributed_fill(self):
        b,a,o,f=evidence();f[0]["order_id"]=10
        self.assertEqual(verify(b,a,o,f)["status"],"unattributed_fill")
    def test_stop_loosened(self):
        b,a,o,f=evidence();a["active_orders"][0]["stop_price"]=99
        self.assertEqual(verify(b,a,o,f)["status"],"stop_loosened")
    def test_incomplete(self):
        self.assertEqual(verify(*evidence(),complete=False)["status"],"incomplete_fills")
