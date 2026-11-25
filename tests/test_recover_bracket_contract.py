import json,unittest
from io import BytesIO
from recover_trading.broker import DeltaDemo,BrokerError
from recover_trading.bracket_contract import fixture_payload,repair_status,verify_fixture

class Opener:
    def open(self,request,timeout):
        return BytesIO(b'{"success":true}')

class BracketContractTests(unittest.TestCase):
    def test_success_only_endpoint_scope(self):
        b=DeltaDemo(opener=Opener())
        self.assertEqual(b._request("POST","/v2/orders/bracket"),{"success":True})
        self.assertEqual(b._request("PUT","/v2/orders/bracket"),{"success":True})
        with self.assertRaises(BrokerError):b._request("POST","/v2/orders")
    def test_fixture_payload_has_no_size_or_entry(self):
        p=fixture_payload(84,-25,100,105,95,"0.1")
        self.assertEqual(p["stop_loss_order"]["stop_price"],"105")
        self.assertNotIn("size",p)
        self.assertNotIn("side",p)
        self.assertNotIn("product_symbol",p)
        with self.assertRaises(ValueError):fixture_payload(84,-25,94,105,95,"0.1")
        with self.assertRaises(ValueError):fixture_payload(84,25,100,95.05,105,"0.1")
    def test_verification_requires_matching_observations(self):
        s={"symbol":"BTCUSD","observed":1000,"positions":[{"product_id":84,"size":-25}],
           "active_orders_complete":True,"active_orders":[]}
        self.assertEqual(repair_status(s,"BTCUSD",1001)["status"],"position_without_active_orders")
        self.assertEqual(verify_fixture(s,"BTCUSD",1001,-25,105,95),"legs_unverified")
        s["active_orders"]=[{"product_id":84,"state":"pending","side":"buy","unfilled_size":25,"reduce_only":True,"bracket_order":True,"stop_order_type":k,"stop_price":p} for k,p in (("stop_loss_order",105),("take_profit_order",95))]
        self.assertEqual(verify_fixture(s,"BTCUSD",1001,-25,105,95),"matching_triggers_observed")
        self.assertEqual(verify_fixture(s,"BTCUSD",1001,-25,106,95),"triggers_mismatch")
        self.assertEqual(verify_fixture(s,"BTCUSD",1001,-50,105,95),"position_changed")
        self.assertEqual(repair_status(s,"BTCUSD",1001)["status"],"existing_bracket_observed")
