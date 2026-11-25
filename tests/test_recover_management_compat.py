import unittest
from recover_trading.management_compat import amendment_response,close_evidence,historical_fills
class ManagementCompatibilityTests(unittest.TestCase):
    def test_acknowledgment_not_amendment_confirmation(self):
        self.assertEqual(amendment_response({"success":True}),"acknowledged_unverified")
        self.assertEqual(amendment_response({"success":False}),"exchange_rejection")
        self.assertEqual(amendment_response({"result":{}}),"unverified")
    def test_partial_and_full_reduce_only_fixture(self):
        order={"id":42,"product_id":84,"side":"buy","reduce_only":True,"size":50,"unfilled_size":20,"state":"cancelled"}
        f={"id":7,"order_id":42,"product_id":84,"side":"buy","size":30}
        self.assertEqual(close_evidence(-50,-20,order,[f],84),"partial_close_observed")
        order.update(unfilled_size=0,state="closed");f["size"]=50
        self.assertEqual(close_evidence(-50,0,order,[f],84),"full_close_observed")
        self.assertEqual(close_evidence(-50,-20,order,[f],84),"position_change_unverified")
        self.assertEqual(close_evidence(-50,0,order,[f,f],84),"fill_identity_unverified")
        order["reduce_only"]=False
        self.assertEqual(close_evidence(-50,0,order,[f],84),"identity_unverified")
    def test_unfilled_or_pending_is_not_close(self):
        o={"id":42,"product_id":84,"side":"sell","reduce_only":True,"size":10,"unfilled_size":10,"state":"pending"}
        self.assertEqual(close_evidence(10,10,o,[],84),"awaiting_terminal")
        o["state"]="cancelled"
        self.assertEqual(close_evidence(10,10,o,[],84),"no_fill_observed")
    def test_historical_reduction_not_order_attribution(self):
        rows=[{"created_at":"2026-11-25T00:00:0"+str(i)+"Z","size":q,"side":s,"new_position":{"size":a}} for i,(q,s,a) in enumerate([(50,"sell",-50),(20,"buy",-30),(30,"buy",0)])]
        self.assertEqual(historical_fills(rows),{"unanchored_or_discontinuous":1,"partial_reduction":1,"flat_after_reduction":1})
