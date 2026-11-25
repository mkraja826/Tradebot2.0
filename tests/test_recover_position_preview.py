import unittest
from recover_trading.position_preview import Simulation,propose,reconcile,observe
class PositionPreviewTests(unittest.TestCase):
    def test_open_ack_not_fill_and_partial_close(self):
        s=propose(Simulation(),"open",side="short",quantity=50)
        self.assertEqual(reconcile(s,observed_size=-50),s)
        with self.assertRaises(ValueError):propose(s,"open",side="short",quantity=50)
        s=reconcile(s,observed_size=-50,terminal=True,bracket_verified=True)
        self.assertEqual(s.size,-50)
        with self.assertRaises(ValueError):propose(s,"open",side="short",quantity=5)
        s=propose(s,"close",quantity=30)
        s=reconcile(s,observed_size=-35,terminal=True,bracket_verified=True)
        self.assertEqual(s.size,-35)
        s=propose(s,"close",quantity=35)
        self.assertEqual(reconcile(s,observed_size=0,terminal=True),Simulation())
    def test_bracket_and_unexpected_reversal(self):
        s=propose(Simulation(50),"update_bracket")
        self.assertEqual(reconcile(s,observed_size=50,terminal=True).phase,"bracket_unverified")
        self.assertEqual(reconcile(s,observed_size=-5,terminal=True).phase,"unexpected_position")
        self.assertEqual(reconcile(s,observed_size=50,terminal=True,bracket_verified=True),Simulation(50))
    def test_realistic_observation(self):
        s={"symbol":"BTCUSD","observed":1000,"positions":[{"product_id":84,"size":-50}],
           "active_orders_complete":True,"active_orders":[{"product_id":84,"state":"pending","side":"buy","unfilled_size":50,"reduce_only":True,"bracket_order":True,"stop_order_type":k,"stop_price":p} for k,p in (("stop_loss_order",60250),("take_profit_order",59450))]}
        a=observe(s,"BTCUSD",1050,12)
        self.assertEqual(a["position_state"],"short")
        self.assertEqual(a["bracket_state"],"matching_legs_observed")
        self.assertEqual(a["unresolved_submissions"],12)
        s["active_orders"][0]["unfilled_size"]=10
        self.assertEqual(observe(s,"BTCUSD",1050)["bracket_state"],"incomplete_or_mismatched_legs")
        self.assertEqual(observe(s,"BTCUSD",1200)["position_state"],"stale_or_invalid")
        self.assertEqual(observe(s,"XAUTUSD",1050)["position_state"],"unavailable")
    def test_incomplete_flat_and_failed_position_read(self):
        s={"symbol":"BTCUSD","observed":1000,"positions":[],"active_orders":[],"active_orders_complete":False}
        self.assertEqual(observe(s,"BTCUSD",1001)["bracket_state"],"unverified")
        s["errors"]={"positions":"BrokerError"}
        self.assertEqual(observe(s,"BTCUSD",1001)["position_state"],"unavailable")
