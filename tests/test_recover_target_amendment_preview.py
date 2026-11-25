import copy,time,unittest
from recover_trading.engine import Journal
from recover_trading.management_executor import ManagementExecutor
from recover_trading.target_amendment_preview import inspect,plan,verify
from test_recover_management_executor import Fake
class TargetPreviewTests(unittest.TestCase):
    def setUp(self):
        self.b=Fake();self.j=Journal(":memory:");self.addCleanup(self.j.close)
        self.e=ManagementExecutor(self.b,self.j);self.now=int(time.time());self.s=self.e.reader.observe("BTCUSD",84);self.product=self.b.product("BTCUSD")
    def test_target_only_contract_and_verification(self):
        p=plan(self.s,"BTCUSD",self.now,self.product,"94.9")
        self.assertEqual(p["payload"],{"id":2,"product_id":84,"size":24,"stop_price":"94.9"})
        self.assertEqual(p["execution_effect"],"none")
        self.assertEqual(verify(p,self.s,self.now),"target_mismatch")
        after=copy.deepcopy(self.s)
        next(r for r in after["active_orders"] if r["id"]==2)["stop_price"]="94.9"
        self.assertEqual(verify(p,after,self.now),"matching_target_and_unchanged_stop_observed")
        next(r for r in after["active_orders"] if r["id"]==1)["stop_price"]="104.9"
        self.assertEqual(verify(p,after,self.now),"stop_changed")
        self.assertEqual(self.b.calls,0)
    def test_wrong_prices_and_identity(self):
        for value in ("95","101","94.95","NaN"):
            with self.assertRaises(ValueError):plan(self.s,"BTCUSD",self.now,self.product,value)
        with self.assertRaises(ValueError):plan(self.s,"BTCUSD",self.now,{**self.product,"id":85},"94.9")
        p=plan(self.s,"BTCUSD",self.now,self.product,"94.9")
        after=copy.deepcopy(self.s);after["positions"][0]["created_at"]="different"
        self.assertEqual(verify(p,after,self.now),"position_or_order_identity_changed")
        self.assertEqual(inspect(self.s,"BTCUSD",self.now+181)["status"],"position_or_bracket_unverified")
    def test_incomplete_or_nonmark_legs(self):
        s=copy.deepcopy(self.s);s["active_orders"][0]["stop_trigger_method"]="last_traded_price"
        self.assertEqual(inspect(s,"BTCUSD",self.now)["status"],"position_or_bracket_unverified")
        s=copy.deepcopy(self.s);s["active_orders"][0]["state"]="open"
        self.assertEqual(inspect(s,"BTCUSD",self.now)["status"],"position_or_bracket_unverified")
