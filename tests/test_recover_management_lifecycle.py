import unittest
from recover_trading.management_lifecycle import plan,current_match,reconcile
from recover_trading.management_shadow import context_for
def snap(q=-25,orders=None):
    return {"symbol":"BTCUSD","observed":1000,"positions":[{"product_id":84,"size":q,"entry_price":"100","mark_price":"101"}] if q else [],
        "active_orders_complete":True,"active_orders":orders or []}
def legs(q,sl=105,tp=95):
    return [{"product_id":84,"state":"pending","side":"buy" if q<0 else "sell","unfilled_size":abs(q),"bracket_order":True,"reduce_only":True,
       "stop_order_type":k,"stop_price":v} for k,v in (("stop_loss_order",sl),("take_profit_order",tp))]
class ManagementLifecycleTests(unittest.TestCase):
    def p(self,action,orders=None,**kw):
        c=context_for({"symbol":"BTCUSD","as_of":1000,"signals":[],"market_context":{}},snap(orders=orders),{"id":84,"symbol":"BTCUSD","tick_size":"0.1"},1001)
        return plan(c,{"symbol":"BTCUSD","action":action,"reason":"fixture",**kw})
    def test_maintain_and_expired(self):
        p=self.p("maintain")
        self.assertEqual(p["expected_size"],-25)
        self.assertEqual(current_match(p,snap(),1001),"matching_observation_not_execution_authority")
        self.assertEqual(current_match(p,snap(),1200),"proposal_expired")
        self.assertEqual(current_match(p,snap(-20),1001),"position_changed")
        self.assertEqual(reconcile(p,snap(),1001)["status"],"no_mutation_requested")
    def test_bracket_repair_and_amendment(self):
        for action,orders in (("repair_bracket",[]),("update_bracket",legs(-25,106,94))):
            p=self.p(action,orders,stop_loss=105,take_profit=95)
            self.assertEqual(reconcile(p,snap(orders=orders),1001,ack={"success":True})["status"],"legs_unverified" if not orders else "triggers_mismatch")
            self.assertEqual(reconcile(p,snap(orders=legs(-25)),1001,ack={"success":True})["status"],"matching_triggers_observed")
            self.assertEqual(reconcile(p,snap(orders=legs(-25)),1001)["status"],"matching_triggers_without_verified_ack")
    def test_reduce_and_residual(self):
        p=self.p("reduce",legs(-25),contracts=5)
        self.assertEqual(p["expected_size"],-20)
        o={"id":42,"product_id":84,"side":"buy","size":5,"unfilled_size":0,"reduce_only":True,"state":"closed"}
        f={"id":"f","order_id":42,"product_id":84,"side":"buy","size":5}
        self.assertEqual(reconcile(p,snap(-20,legs(-20)),1001,order=o,fills=[f],complete_fills=True)["status"],"partial_close_observed")
        self.assertEqual(reconcile(p,snap(-20,legs(-25)),1001,order=o,fills=[f],complete_fills=True)["status"],"reduction_bracket_unverified")
        self.assertEqual(reconcile(p,snap(-20),1001,order=o,fills=[f])["status"],"fill_window_unverified")
    def test_close_with_residual_orders(self):
        p=self.p("close",legs(-25))
        o={"id":42,"product_id":84,"side":"buy","size":25,"unfilled_size":0,"reduce_only":True,"state":"closed"}
        f={"id":"f","order_id":42,"product_id":84,"side":"buy","size":25}
        self.assertEqual(reconcile(p,snap(0),1001,order=o,fills=[f],complete_fills=True)["status"],"full_close_observed")
        self.assertEqual(reconcile(p,snap(0,legs(-25)),1001,order=o,fills=[f],complete_fills=True)["status"],"flat_residual_orders_unverified")
