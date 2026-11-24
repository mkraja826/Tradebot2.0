import unittest,os
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.owner_connectivity_bridge_v3 import AccountReader,publish,read_report,FILENAME
from tradebot.model_wire_v3 import MODEL_IDS
from test_signed_account_context_v3 import Broker,NOW
class OwnerBridgeTests(unittest.TestCase):
    def test_fixed_get_surface(self):
        b=Broker(); r=AccountReader(b,"BTCUSD")
        for method,path,auth in [("POST","/v2/orders",True),("GET","/v2/products/XAUTUSD",False),("GET","/v2/products/84/orders/leverage",True),("GET","/v2/users/trading_preferences",False)]:
            with self.assertRaises(ValueError): r._request(method,path,auth)
        self.assertEqual(b.calls,[])
        with self.assertRaises(ValueError): AccountReader(Broker(parent=True)).wallet_balances()
        b.allow_orders=True
        with self.assertRaises(ValueError): AccountReader(b,"BTCUSD")
    def test_export_and_freshness(self):
        calls=[]
        class Catalogue:
            def _call(self,url,*,timeout):
                calls.append(url)
                assert url.endswith("/models")
                return {"data":[{"id":x} for x in MODEL_IDS.values()]}
        with TemporaryDirectory() as d:
            p=Path(d)
            r=publish(p,children={"BTCUSD":Broker()},parent=Broker(parent=True),provider=Catalogue(),clock=lambda:NOW)
            self.assertEqual(len(calls),1)
            self.assertEqual(r["markets"]["BTCUSD"]["account_status"],"signed_read_only")
            self.assertTrue(r["markets"]["BTCUSD"]["account"]["configured_leverage_observed"])
            self.assertEqual(r["markets"]["XAUTUSD"]["account_status"],"not_provisioned")
            self.assertFalse(r["execution_authorized"])
            t=int(NOW.timestamp())
            x=read_report(p,now=t)
            self.assertTrue(x["markets"]["BTCUSD"]["account_evidence_fresh"])
            self.assertFalse(x["markets"]["XAUTUSD"]["account_evidence_fresh"])
            self.assertTrue(x["markets"]["XAUTUSD"]["model_listed"])
            self.assertEqual(read_report(p,now=t+91)["status"],"unavailable_or_stale")
            os.chmod(p/FILENAME,0o644)
            self.assertEqual(read_report(p,now=t)["status"],"unavailable_or_stale")
    def test_gold_and_missing(self):
        with TemporaryDirectory() as d:
            r=publish(d,children={"XAUTUSD":Broker("XAUTUSD")},parent=Broker("XAUTUSD",parent=True),provider=None,clock=lambda:NOW)
            self.assertEqual(r["markets"]["XAUTUSD"]["account_status"],"signed_read_only")
            self.assertIsNone(r["markets"]["XAUTUSD"]["model_listed"])
            self.assertFalse(r["markets"]["XAUTUSD"]["completion_verified"])
