import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.ai_decision_v3 import prepare
from tradebot.model_wire_v3 import build_request,MODEL_IDS,parse_fixture
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.m15_decision_validation_v3 import envelope
from tradebot.product_context_v3 import product_spec
from test_model_wire_v3 import raw,NOW,scan,ctx
class RouteMigrationTests(unittest.TestCase):
    def test_new_and_historical(self):
        with TemporaryDirectory() as d:
            event=OpportunityJournal(Path(d)/"j.sqlite").record(scan(),ctx())
        self.assertEqual(event["model_if_enabled"],"GPT-6.1 Sol")
        old=dict(event,model_if_enabled="GPT-6")
        spec=product_spec(raw("BTCUSD"),"BTCUSD",NOW)
        for e,m in ((event,"tb-gpt-6-1-sol"),(old,"tb-gpt-6")):
            q=prepare(e)
            self.assertEqual(q["model_if_enabled"],e["model_if_enabled"])
            w=build_request(e,spec,now=NOW)
            self.assertEqual(w["body"]["model"],m)
            r=envelope(w,wait_fixture(w["request"]))
            self.assertEqual(parse_fixture(r,w)["action"],"WAIT")
            with self.assertRaises(ValueError): parse_fixture(dict(r,model="unknown"),w)
        self.assertEqual(MODEL_IDS["XAUTUSD"],"tb-deepseek-v4-1-flash")
        with self.assertRaises(ValueError): prepare(dict(event,model_if_enabled="DeepSeek"))
