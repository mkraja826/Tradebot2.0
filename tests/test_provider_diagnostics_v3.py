import unittest,json
from tempfile import TemporaryDirectory
from tradebot.provider_diagnostics_v3 import classify,envelope_shape
from tradebot.product_context_v3 import product_spec
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.m15_decision_validation_v3 import envelope
from test_model_wire_v3 import raw,NOW
from paid_decision_test_v3 import fixture,execute,receipt_name
class DiagnosticsTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(ValueError("unexpected_model"),"validation"),"unexpected_model")
        self.assertEqual(classify(ValueError("private dummy text"),"validation"),"unclassified_validation_failure")
        self.assertEqual(classify(json.JSONDecodeError("bad","dummy",0),"validation"),"invalid_json")
    def test_shape(self):
        r=envelope_shape({"model":"unknown","choices":[{"finish_reason":"dummy private","message":{"content":"dummy private"}}]},"expected")
        self.assertFalse(r["model_matches"])
        self.assertNotIn("dummy",json.dumps(r))
    def test_budget_and_failure(self):
        s="BTCUSD"
        w=fixture(s,product_spec(raw(s),s,NOW),NOW)
        response=envelope(w,wait_fixture(w["request"]))
        response["choices"][0]["finish_reason"]="length"
        class Stub:
            calls=0
            def _call(self,*a,**kw):
                self.calls+=1
                return response
        c=Stub()
        with TemporaryDirectory() as d:
            r=execute(d,s,w,c,clock=lambda:NOW,attempt=2)
            self.assertEqual(r["failure_code"],"incomplete_response")
            self.assertFalse(r["execution_authorized"])
            with self.assertRaises(FileExistsError): execute(d,s,w,c,attempt=2)
            with self.assertRaises(ValueError): execute(d,s,w,c,attempt=5)
            with self.assertRaises(ValueError): receipt_name("XAUTUSD",2)
            self.assertEqual(c.calls,1)
