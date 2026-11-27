import unittest
from recover_trading.gold_v2_entry_adapter import plan,prepare,submit_prepared

NOW=3600020
PRODUCT={"symbol":"XAUTUSD","id":42,"contract_unit_currency":"XAUT","settling_asset":{"symbol":"USD"},
         "quoting_asset":{"symbol":"USD"},"notional_type":"vanilla","tick_size":"0.1","contract_value":"0.01"}
WALLET={"asset_symbol":"USD","user_id":"123","balance":"100","available_balance":"80"}
QUOTE={"status":"fresh_book","best_bid":"2999","best_ask":"3000","mark_price":"2999.5"}
def report(side="LONG"):
    return {"symbol":"XAUTUSD","status":"observed","as_of":3600000,"decision_as_of":NOW-1,
            "candidates":[{"family":"trend_pullback","direction":side,"atr":2,
                           "stop_distance_atr_hypothesis":1.5,"target_distance_atr_hypothesis":3}]}
def make(r=None,p=None,w=None,q=None):
    return plan(report() if r is None else r,PRODUCT if p is None else p,WALLET if w is None else w,
                QUOTE if q is None else q,allocation_fraction=.1,now=NOW)
class ReadBroker:
    def wallet(self):return {"result":[WALLET]}
    def product(self,symbol):return PRODUCT
    def positions(self,pid):return [{"product_id":pid,"size":0}]
    def active_orders_page(self,pid):return {"result":[],"meta":{}}
    def ticker(self,symbol):
        return {"symbol":symbol,"product_id":42,"timestamp":NOW*1000000,"mark_price":"2999.5",
                "quotes":{"best_bid":"2999","best_ask":"3000"}}

class AdapterTests(unittest.TestCase):
    def test_long(self):
        p=make()["proposal"]
        self.assertEqual((p["side"],p["size"],p["leverage"]),("buy",6,20))
        self.assertEqual((p["stop_loss"],p["take_profit"]),(2997,3006))
    def test_short(self):
        p=make(report("SHORT"))["proposal"]
        self.assertEqual((p["side"],p["stop_loss"],p["take_profit"]),("sell",3002,2993))
    def test_same_bar_id(self):
        self.assertEqual(make()["decision_id"],make(report("SHORT"))["decision_id"])
    def test_conflicting_candidates(self):
        r=report();r["candidates"]+=report("SHORT")["candidates"]
        self.assertEqual(make(r)["status"],"conflicting_candidates")
    def test_stale(self):
        r=report();r["as_of"]-=300;r["decision_as_of"]-=300
        self.assertEqual(make(r)["status"],"stale_candidate")
    def test_wrong_symbol(self):
        with self.assertRaises(ValueError):make(dict(report(),symbol="BTCUSD"))
    def test_wrong_product(self):
        with self.assertRaises(ValueError):make(p=dict(PRODUCT,contract_unit_currency="BTC"))
    def test_insufficient_size(self):
        self.assertEqual(make(w=dict(WALLET,available_balance="0.01"))["status"],"below_one_contract")
    def test_crossed_mark(self):
        self.assertEqual(make(q=dict(QUOTE,mark_price="3010"))["status"],"incompatible_bracket")
    def test_prepare(self):
        r,a=prepare(ReadBroker(),report(),expected_gold_account="123",allocation_fraction=.1,clock=lambda:NOW)
        self.assertEqual(r["status"],"proposed")
        self.assertEqual(a["product"]["symbol"],"XAUTUSD")
    def test_account_mismatch(self):
        with self.assertRaises(ValueError):prepare(ReadBroker(),report(),expected_gold_account="124",allocation_fraction=.1,clock=lambda:NOW)
    def test_existing_exposure(self):
        class Open(ReadBroker):
            def positions(self,pid):return [{"product_id":pid,"size":1}]
        r,_=prepare(Open(),report(),expected_gold_account="123",allocation_fraction=.1,clock=lambda:NOW)
        self.assertEqual(r["status"],"existing_exposure")
    def test_disabled_dispatch(self):
        self.assertEqual(submit_prepared(None,report(),expected_gold_account="123",allocation_fraction=.1)["status"],"disabled")
