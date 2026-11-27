import unittest
from hashlib import sha256
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_management_adapter import evaluate

NOW=3600020
BOUND=3600000
PRODUCT={"symbol":"XAUTUSD","id":42,"tick_size":"0.1"}
def fixture(side=1,closes=(101,102),mark=None):
    decision=sha256(f"gold-v2:{BOUND-900}".encode()).hexdigest()
    cid=sha256(("recover:"+decision).encode()).hexdigest()[:32]
    sl,tp=(98,106) if side==1 else (102,94)
    direction="buy" if side==1 else "sell"
    entry={"signal_boundary":BOUND-900,"journal_client_id":cid,
           "verified_position_created_at":"fixture-time","first_full_bar_close":BOUND-300,"signal_atr":1,
           "intent":{"product_id":42,"side":direction,"size":4,"stop_loss":sl,"take_profit":tp},
           "receipt":{"id":9,"client_order_id":cid,"product_id":42,"side":direction,"size":4,"unfilled_size":0,
                      "state":"closed","reduce_only":False,"average_fill_price":100,
                      "bracket_stop_loss_price":sl,"bracket_take_profit_price":tp}}
    orders=[{"id":i,"product_id":42,"state":"open","side":"sell" if side==1 else "buy",
             "stop_order_type":kind,"stop_price":price,"unfilled_size":4,"reduce_only":True,
             "bracket_order":True,"stop_trigger_method":"mark_price"}
             for i,(kind,price) in enumerate((("stop_loss_order",sl),("take_profit_order",tp)),1)]
    snapshot={"symbol":"XAUTUSD","observed":NOW,"positions":[{"product_id":42,"size":4*side,
              "entry_price":100,"mark_price":closes[-1] if mark is None else mark,"created_at":"fixture-time"}],
              "active_orders":orders,"active_orders_complete":True}
    report={"symbol":"XAUTUSD","status":"observed","as_of":BOUND,"decision_as_of":NOW-1,
            "features":{300:{"atr":1,"ema":[100,100,100,100]}}}
    bars=[Bar(BOUND-300+i*300,c-side*.3,c+.5,c-.5,c,1) for i,c in enumerate(closes)]
    return report,snapshot,entry,bars
def run(r,s,e,b):
    return evaluate(r,s,PRODUCT,e,now=NOW,history=b)

class ManagementTests(unittest.TestCase):
    def test_long_stop_tightens(self):
        r,s,e,b=fixture()
        x=run(r,s,e,b)
        self.assertEqual(x["proposal"]["action"],"update_bracket")
        self.assertGreater(x["proposal"]["stop_loss"],98)
        self.assertEqual(x["proposal"]["take_profit"],106)
        self.assertEqual(x["execution_effect"],"none")
    def test_short_stop_tightens(self):
        r,s,e,b=fixture(-1,(99,98))
        x=run(r,s,e,b)
        self.assertLess(x["proposal"]["stop_loss"],102)
        self.assertEqual(x["proposal"]["take_profit"],94)
    def test_giveback_priority(self):
        r,s,e,b=fixture(closes=(102,101))
        self.assertEqual(run(r,s,e,b)["proposal"]["action"],"close")
    def test_adverse_reduction(self):
        r,s,e,b=fixture(closes=(99.8,99.3))
        x=run(r,s,e,b)
        self.assertEqual(x["proposal"]["action"],"reduce")
        self.assertEqual(x["proposal"]["contracts"],2)
    def test_legacy_position_not_adopted(self):
        r,s,e,b=fixture();e["journal_client_id"]="legacy"
        self.assertEqual(run(r,s,e,b)["status"],"ownership_or_protection_unverified")
    def test_changed_size_not_adopted(self):
        r,s,e,b=fixture();s["positions"][0]["size"]=2
        self.assertEqual(run(r,s,e,b)["status"],"ownership_or_protection_unverified")
    def test_missing_bracket(self):
        r,s,e,b=fixture();s["active_orders"].pop()
        self.assertEqual(run(r,s,e,b)["status"],"ownership_or_protection_unverified")
    def test_missing_history(self):
        r,s,e,b=fixture()
        self.assertEqual(run(r,s,e,b[1:])["status"],"episode_history_unverified")
    def test_stale_signal(self):
        r,s,e,b=fixture();r["decision_as_of"]=BOUND-300
        self.assertEqual(run(r,s,e,b)["status"],"market_data_stale")
    def test_wrong_symbol(self):
        r,s,e,b=fixture();r["symbol"]="BTCUSD"
        with self.assertRaises(ValueError):run(r,s,e,b)
    def test_target_extension_only_when_no_stop_change(self):
        r,s,e,b=fixture(closes=(103.5,104.5))
        s["active_orders"][0]["stop_price"]=104
        x=run(r,s,e,b)
        self.assertEqual(x["proposal"]["action"],"update_bracket")
        self.assertEqual(x["proposal"]["stop_loss"],104)
        self.assertEqual(x["proposal"]["take_profit"],107)
