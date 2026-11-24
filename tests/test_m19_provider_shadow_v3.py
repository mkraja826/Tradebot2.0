import unittest,json
from pathlib import Path
from tempfile import TemporaryDirectory
from tradebot.m19_provider_shadow_v3 import Campaign,dispatch
from tradebot.opportunity_journal_v3 import OpportunityJournal,canonical
from tradebot.product_context_v3 import product_spec
from test_model_wire_v3 import scan,ctx,sig,raw,NOW
class ProviderShadowTests(unittest.TestCase):
    def setUp(self):
        self.d=TemporaryDirectory();self.addCleanup(self.d.cleanup)
        self.p=Path(self.d.name)
        j=OpportunityJournal(self.p/"events.sqlite")
        self.events={s:j.record(scan(s,[sig(r)]),ctx(s)) for s,r in (("BTCUSD","B01"),("XAUTUSD","G01"))}
        self.calls=[]
    def stub(self,url,body,headers,timeout):
        self.calls.append(body["model"])
        p=json.loads(body["messages"][-1]["content"])
        self.assertEqual(p["account"]["mode"],"synthetic_fixture")
        r=dict(schema_version=p["schema_version"],event_id=p["event_id"],symbol=p["symbol"],
            action="LONG",rationale="Paper fixture",plan=dict(entry_type="MARKET",entry_reference=100,
            contracts=1,leverage=1,margin_quote=0.1,stop_loss=99,take_profit=102,holding_minutes=15,management="Paper"))
        if p["symbol"]=="BTCUSD":
            self.assertTrue(url.endswith("/v1/messages"))
            self.assertEqual(headers["anthropic-version"],"2023-06-01")
            return dict(model=body["model"],type="message",role="assistant",stop_reason="end_turn",content=[dict(type="text",text=canonical(r))])
        self.assertTrue(url.endswith("/v1/chat/completions"))
        return dict(model=body["model"],choices=[dict(finish_reason="stop",message=dict(role="assistant",content=canonical(r)))])
    def run_event(self,c,s,transport=None):
        return dispatch(c,self.events[s],product_spec(raw(s),s,NOW),transport=transport or self.stub,clock=lambda:NOW)
    def test_routes_and_restart(self):
        c=Campaign(self.p/"campaign.sqlite",request_limit=2)
        for s in self.events:
            r=self.run_event(c,s)
            self.assertEqual(r["status"],"validated_paper_proposal")
            self.assertEqual(r["decision"]["action"],"LONG")
            self.assertFalse(r["execution_authorized"])
        c=Campaign(c.path,request_limit=2)
        self.assertEqual(self.run_event(c,"BTCUSD")["status"],"duplicate")
        self.assertEqual(len(self.calls),2)
        self.assertEqual(c.counts()["remaining"],0)
        with self.assertRaises(ValueError):Campaign(c.path,request_limit=3)
    def test_failure_consumes_budget(self):
        c=Campaign(self.p/"campaign.sqlite",request_limit=1)
        def fail(*args):raise TimeoutError()
        r=self.run_event(c,"BTCUSD",fail)
        self.assertEqual(r["status"],"transport_outcome_unknown")
        self.assertEqual(r["failure_code"],"provider_timeout")
        self.assertFalse(r["execution_authorized"])
        self.assertEqual(self.run_event(c,"BTCUSD")["status"],"duplicate")
        self.assertEqual(self.run_event(c,"XAUTUSD")["status"],"budget_exhausted")
        self.assertFalse(self.calls)
    def test_identity_mismatch(self):
        c=Campaign(self.p/"campaign.sqlite",request_limit=1)
        def wrong(*args):return {"model":"unknown"}
        self.assertEqual(self.run_event(c,"BTCUSD",wrong)["status"],"response_rejected")
