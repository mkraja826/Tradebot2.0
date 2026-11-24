import unittest,json
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.m27_decision_reliability_v3 import review
from tradebot.model_wire_v3 import build_request,MODEL_IDS
from tradebot.product_context_v3 import product_spec
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.ai_replay_v3 import wait_fixture
from test_model_wire_v3 import raw
from test_opportunity_scanner_v3 import scan,ctx,sig,NOW
from test_m18_text_wire_v3 import TextWireTests
from tradebot.messages_wire_v3 import build,MODEL

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        j=OpportunityJournal(Path(self.tmp.name)/"j.sqlite")
        s="XAUTUSD";e=j.record(scan(s,[sig("G01")]),ctx(s))
        self.w=build_request(e,product_spec(raw(s),s,NOW),now=NOW)
        self.r=wait_fixture(self.w["request"])
    def envelope(self,raw):
        return dict(model=MODEL_IDS["XAUTUSD"],choices=[dict(finish_reason="stop",message=dict(role="assistant",content=raw))])
    def assert_wait(self,x):
        self.assertEqual(x["action"],"WAIT")
        self.assertEqual(x["origin"],"local_failure_wait")
        self.assertFalse(x["provider_response_validated"])
        self.assertFalse(x["retry_authorized"])
        self.assertFalse(x["execution_authorized"])
    def test_valid(self):
        r=review(self.w,self.envelope(json.dumps(self.r)),now=NOW)
        self.assertTrue(r["provider_response_validated"])
        self.assertEqual(r["action"],"WAIT")
    def test_bad_payloads(self):
        for raw in ("not json",'{"action":"WAIT","action":"LONG"}','{"x":NaN}',json.dumps(dict(self.r,event_id="wrong")),json.dumps(dict(self.r,symbol="BTCUSD"))):
            self.assert_wait(review(self.w,self.envelope(raw),now=NOW))
    def test_unknown_and_stale(self):
        self.assert_wait(review(self.w,None,now=NOW))
        self.assert_wait(review(self.w,self.envelope(json.dumps(self.r)),now=NOW+151))
    def test_btc_messages(self):
        w=TextWireTests().make("BTCUSD");w["body"]["model"]=MODEL
        body=build(w)
        e=dict(model=MODEL,type="message",role="assistant",stop_reason="end_turn",content=[dict(type="text",text=json.dumps(wait_fixture(w["request"])))])
        self.assertTrue(review(w,e,now=w["request"]["payload"]["as_of"],messages_body=body)["provider_response_validated"])
        self.assert_wait(review(w,dict(e,stop_reason="max_tokens"),now=w["request"]["payload"]["as_of"],messages_body=body))
