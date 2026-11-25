import unittest
from recover_trading.management_test import baseline,scenarios
class ControlledManagementTests(unittest.TestCase):
    def fixture(self,qty):
        side="sell" if qty>0 else "buy"
        s={"symbol":"BTCUSD","observed":1000,"positions":[{"product_id":84,"size":qty}],
           "active_orders_complete":True,"active_orders":[{"id":i,"product_id":84,"state":"pending","side":side,"size":abs(qty),"unfilled_size":abs(qty),"reduce_only":True,"bracket_order":True,"stop_order_type":k,"stop_price":p} for i,k,p in ((1,"stop_loss_order",105),(2,"take_profit_order",95))]}
        r={"id":3,"product_id":84,"side":"buy" if qty>0 else "sell","state":"closed","size":abs(qty),"unfilled_size":0,"bracket_stop_loss_price":105,"bracket_take_profit_price":95}
        return s,[r]
    def test_both_position_directions(self):
        for qty in (50,-100):
            s,r=self.fixture(qty)
            b,checks=scenarios(s,"BTCUSD",r,1001)
            self.assertEqual(b["matching_entry_receipts"],1)
            self.assertEqual(b["amendment_target"],"unverified")
            self.assertEqual(len(checks),10)
            self.assertTrue(all(x["passed"] for x in checks))
    def test_stale_or_duplicate_leg_ids(self):
        s,r=self.fixture(-50)
        self.assertEqual(scenarios(s,"BTCUSD",r,1200)[1],[])
        s["active_orders"][1]["id"]=1
        self.assertEqual(baseline(s,"BTCUSD",r,1001)["status"],"leg_identity_unverified")
