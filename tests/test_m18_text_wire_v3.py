import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.model_wire_v3 import build_text_fixture,parse_fixture
from tradebot.product_context_v3 import product_spec
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.m15_decision_validation_v3 import envelope
from test_model_wire_v3 import raw,NOW,scan,ctx,sig
class TextWireTests(unittest.TestCase):
    def make(self,s):
        with TemporaryDirectory() as d:
            e=OpportunityJournal(Path(d)/"fixture.sqlite").record(scan(s,[sig("B01" if s=="BTCUSD" else "G01")]),ctx(s))
        a=dict(symbol=s,mode="synthetic_fixture",net_equity_usd="100",available_margin_usd="80",positions=[],open_order_count=0)
        return build_text_fixture(e,product_spec(raw(s),s,NOW),a,now=NOW)
    def test_text_contract(self):
        w=self.make("BTCUSD")
        self.assertNotIn("response_format",w["body"])
        self.assertEqual(w["body"]["max_completion_tokens"],1024)
        self.assertFalse(w["execution_authorized"])
        r=envelope(w,wait_fixture(w["request"]))
        self.assertEqual(parse_fixture(r,w)["action"],"WAIT")
        with self.assertRaises(ValueError): parse_fixture(dict(r,model="unverified-alias"),w)
        w["body"]["max_completion_tokens"]=2048
        with self.assertRaises(ValueError): parse_fixture(r,w)
    def test_gold_unchanged(self):
        with self.assertRaises(ValueError): self.make("XAUTUSD")
