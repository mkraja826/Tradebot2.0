import unittest
from recover_trading.engine import Journal
from recover_trading.management_shadow import ManagementShadow,context_for,validate
class Provider:
    def __init__(self,action):self.action=action;self.calls=0
    def propose_management(self,model,context):self.calls+=1;return {"symbol":context["symbol"],"reason":"fixture",**self.action}
def fixture():
    s={"symbol":"BTCUSD","observed":1000,"positions":[{"product_id":84,"size":-25,"entry_price":"100","mark_price":"101"}],"active_orders_complete":True,"active_orders":[]}
    r={"symbol":"BTCUSD","as_of":1000,"signals":[],"market_context":{}}
    p={"symbol":"BTCUSD","id":84,"tick_size":"0.1"}
    return r,s,p
class ManagementShadowTests(unittest.TestCase):
    def test_actions_and_geometry(self):
        r,s,p=fixture();c=context_for(r,s,p,1001)
        def v(a,**kw):return validate({"symbol":"BTCUSD","action":a,"reason":"fixture",**kw},c)
        self.assertEqual(v("maintain")["action"],"maintain")
        self.assertEqual(v("close")["action"],"close")
        self.assertEqual(v("reduce",contracts=5)["contracts"],5)
        self.assertEqual(v("repair_bracket",stop_loss=105,take_profit=95)["stop_loss"],105)
        for a,kw in [("reduce",{"contracts":25}),("open",{}),("close",{"size":1}),("update_bracket",{"stop_loss":105,"take_profit":95}),("repair_bracket",{"stop_loss":100,"take_profit":95}),("repair_bracket",{"stop_loss":105.05,"take_profit":95})]:
            with self.assertRaises(ValueError):v(a,**kw)
    def test_capture_then_separate_evaluation(self):
        j=Journal(":memory:");self.addCleanup(j.close);m=ManagementShadow(j.db)
        r,s,p=fixture();a=m.capture(r,s,"mock",lambda _:p,1001)
        self.assertEqual(a["status"],"prepared")
        b=m.capture(r,s,"mock",lambda _:p,1002)
        self.assertEqual(a["id"],b["id"])
        provider=Provider({"action":"close"})
        self.assertEqual(m.evaluate(a["id"],provider)["status"],"proposed")
        self.assertEqual(m.evaluate(a["id"],provider)["status"],"not_prepared")
        self.assertEqual(provider.calls,1)
        self.assertEqual(j.db.execute("SELECT count(*) FROM orders").fetchone()[0],0)
    def test_stale_snapshot_not_captured(self):
        r,s,p=fixture()
        self.assertIsNone(context_for(r,s,p,1200))

    def test_rounded_scan_cutoff(self):
        r,s,p=fixture()
        r["as_of"]=1001
        self.assertIsNotNone(context_for(r,s,p,1000))
        r["as_of"]=1002
        self.assertIsNone(context_for(r,s,p,1000))

    def test_provider_failure_code_recorded(self):
        from recover_trading.decision import ProviderResponseError
        class Failing:
            def propose_management(self,model,context):raise ProviderResponseError("http_520")
        j=Journal(":memory:");self.addCleanup(j.close);m=ManagementShadow(j.db)
        r,s,p=fixture();a=m.capture(r,s,"mock",lambda _:p,1001)
        self.assertEqual(m.evaluate(a["id"],Failing())["response_error"],"http_520")
