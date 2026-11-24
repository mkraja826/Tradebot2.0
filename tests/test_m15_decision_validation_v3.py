import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.m15_decision_validation_v3 import tick,exercise
from tradebot.model_wire_v3 import MODEL_IDS,build_synthetic_fixture,build_request,parse_fixture
from tradebot.product_context_v3 import product_spec,account_unavailable
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.m15_decision_validation_v3 import envelope
from test_model_wire_v3 import raw
from test_opportunity_scanner_v3 import NOW,scan,ctx,sig
class DecisionValidationTests(unittest.TestCase):
    def test_all_routes_and_actual_preview(self):
        with TemporaryDirectory() as d:
            j=OpportunityJournal(Path(d)/"opportunities-v3.sqlite")
            for s in MODEL_IDS:
                signal=sig("B01" if s=="BTCUSD" else "G01")
                c=dict(ctx(s),strategy_learning={"status":"research_advisory","profiles":[]})
                j.record(scan(s,[signal]),c)
            specs=lambda:{s:{"status":"ready","data":product_spec(raw(s),s,NOW)} for s in MODEL_IDS}
            r=tick(d,spec_reader=specs,account_reader=lambda:{s:account_unavailable(s) for s in MODEL_IDS},clock=lambda:NOW)
            for v in r["markets"].values():
                self.assertEqual(v["fixture"]["actions"],["WAIT","LONG","SHORT"])
                self.assertEqual(v["actual_opportunity_preview"],"offline_wait_passed")
                self.assertFalse(v["authenticated_model_verified"])
            self.assertFalse(r["execution_authorized"])
            self.assertEqual(j.counts()["BTCUSD"]["events"],1)
    def test_fixture_isolation(self):
        with TemporaryDirectory() as d:
            e=OpportunityJournal(Path(d)/"j.sqlite").record(scan(),ctx())
            p=product_spec(raw("BTCUSD"),"BTCUSD",NOW)
            a={"symbol":"BTCUSD","mode":"synthetic_fixture"}
            w=build_synthetic_fixture(e,p,a,now=NOW)
            self.assertEqual(w["mode"],"synthetic_wire_fixture")
            r=wait_fixture(w["request"])
            self.assertEqual(parse_fixture(envelope(w,r),w),r)
            with self.assertRaises(ValueError): parse_fixture(envelope(w,r),dict(w,mode="offline_wire_preview"))
            with self.assertRaises(ValueError): build_synthetic_fixture(e,p,dict(a,symbol="XAUTUSD"),now=NOW)
            with self.assertRaises(ValueError): build_synthetic_fixture(e,p,a,now=NOW+151)
            with self.assertRaises(ValueError): build_request(e,p,now=NOW,account_context=a)
