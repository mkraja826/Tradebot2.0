import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.connectivity_v3 import probe_clients,refresh
from tradebot.model_wire_v3 import MODEL_IDS
from tradebot.product_context_v3 import account_unavailable,product_spec
from tradebot.opportunity_journal_v3 import OpportunityJournal
from test_signed_account_context_v3 import Broker,NOW
from test_model_wire_v3 import raw
class Catalogue:
    def _call(self,url,*,timeout):
        assert url.endswith("/models")
        return {"data":[{"id":MODEL_IDS["BTCUSD"]}]}
class ConnectivityTests(unittest.TestCase):
    def test_injected_clients(self):
        for s in MODEL_IDS:
            child=Broker(s); parent=Broker(s,parent=True)
            r=probe_clients({s:child},parent,Catalogue(),clock=lambda:NOW)
            self.assertTrue(r["markets"][s]["signed_wallet_verified"])
            self.assertFalse(r["markets"][s]["leverage_limit_verified"])
            self.assertTrue(r["markets"]["BTCUSD"]["catalogue_available"])
            self.assertFalse(r["markets"]["XAUTUSD"]["catalogue_available"])
            self.assertFalse(r["execution_authorized"])
            self.assertEqual(r["paid_ai_requests"],0)
    def test_missing_and_orders_enabled_clients(self):
        b=Broker(); b.allow_orders=True
        r=probe_clients({"BTCUSD":b},Broker(parent=True),None,clock=lambda:NOW)
        for x in r["markets"].values():
            self.assertFalse(x["signed_wallet_verified"])
            self.assertIsNone(x["catalogue_available"])
    def test_refresh_partial(self):
        with TemporaryDirectory() as d:
            root=Path(d); OpportunityJournal(root/"opportunities-v3.sqlite")
            t=int(NOW.timestamp())
            r=refresh(root,account_reader=lambda:{s:account_unavailable(s) for s in MODEL_IDS},
              spec_reader=lambda:{s:{"status":"ready","data":product_spec(raw(s),s,t)} for s in MODEL_IDS},clock=lambda:t)
            self.assertFalse(r["live_ai_verified"])
            self.assertTrue((root/"connectivity-v3.json").exists())
            self.assertEqual(r["markets"]["BTCUSD"]["opportunity_status"],"no_opportunity")
