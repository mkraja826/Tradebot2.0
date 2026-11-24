import unittest,json,copy
from tempfile import TemporaryDirectory
from tradebot.m15_provider_connectivity_v3 import tick
from tradebot.model_wire_v3 import MODEL_IDS,parse_fixture,catalogue_status
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.product_context_v3 import product_spec
from test_model_wire_v3 import raw,WireTests,NOW
class ProviderCommissioningTests(unittest.TestCase):
    def test_catalogue_only_and_offline_routes(self):
        calls=[]
        class Client:
            def _call(self,url,*,timeout):
                calls.append(url)
                assert url.endswith("/models")
                return {"data":[{"id":MODEL_IDS["BTCUSD"]}]}
        specs=lambda:{s:{"status":"ready","data":product_spec(raw(s),s,NOW)} for s in MODEL_IDS}
        with TemporaryDirectory() as d:
            r=tick(d,provider=Client(),spec_reader=specs,clock=lambda:NOW)
            self.assertEqual(len(calls),1)
            self.assertTrue(r["markets"]["BTCUSD"]["catalogue_model_listed"])
            self.assertFalse(r["markets"]["XAUTUSD"]["catalogue_model_listed"])
            for x in r["markets"].values():
                self.assertEqual(x["compatibility"]["status"],"passed")
                self.assertFalse(x["actual_completion_verified"])
            self.assertFalse(r["execution_authorized"])
            self.assertEqual(r["paid_ai_requests"],0)
            r=tick(d,spec_reader=specs,clock=lambda:NOW)
            self.assertEqual(r["catalogue_status"],"not_provisioned")
            self.assertIsNone(r["markets"]["BTCUSD"]["catalogue_model_listed"])
    def test_invalid_catalogues(self):
        for data in ([{"id":"x"},{"id":"x"}],[{"id":[]}],[{}],[None]):
            with self.assertRaises(ValueError): catalogue_status({"data":data})
    def test_wire_integrity_and_message_rejections(self):
        f=WireTests();f.setUp();self.addCleanup(f.doCleanups)
        for event in (f.b,f.g):
            w=f.wire(event); r=wait_fixture(w["request"])
            e={"model":w["body"]["model"],"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":json.dumps(r)}}]}
            self.assertEqual(parse_fixture(e,w),r)
            for fields in ({"refusal":"no"},{"tool_calls":[{}]},{"role":"user"},{"content":"NaN"},{"content":None}):
                bad=copy.deepcopy(e);bad["choices"][0]["message"].update(fields)
                with self.assertRaises(ValueError): parse_fixture(bad,w)
            bad=copy.deepcopy(w);bad["body"]["messages"][1]["content"]="{}"
            with self.assertRaises(ValueError): parse_fixture(e,bad)
            bad=copy.deepcopy(w);bad["request"]["request_sha256"]="bad"
            with self.assertRaises(ValueError): parse_fixture(e,bad)
