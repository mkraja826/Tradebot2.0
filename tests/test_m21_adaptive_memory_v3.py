import unittest,json,tempfile
from pathlib import Path
from unittest.mock import patch
from tradebot.m21_adaptive_memory_v3 import freeze
from tradebot.ai_decision_v3 import prepare
from tradebot.opportunity_journal_v3 import digest
class AdaptiveMemoryTests(unittest.TestCase):
 def setUp(self):
    self.d=tempfile.TemporaryDirectory();self.addCleanup(self.d.cleanup)
    self.root=Path(self.d.name);self.p=self.root/"m21-paper-learning-v3.json"
    self.c=dict(symbol="BTCUSD",as_of=1000,context_observed_at=1000,market={"frames":{}})
    self.sig=dict(id="B01",frame="5m",direction="LONG")
    self.o=dict(symbol="BTCUSD",event_id="prior",rule_id="B01",frame="5m",direction="LONG",status="observed",horizon_minutes=15,reference_start=50,reference_end=950,directional_return_pct=.5,favorable_excursion_pct=1,adverse_excursion_pct=.2,regime={})
    self.r=dict(mode="paper_learning_diagnostic_only",checked_at=990,execution_authorized=False,orders_submitted=0,paid_ai_requests=0,verified_trade_outcomes=0,records=[dict(symbol="BTCUSD",event_id="prior",action="WAIT",actual_trade_outcome=False,signal_paths=[self.o])])
 def save(self):self.p.write_text(json.dumps(self.r))
 def run_freeze(self):return freeze(self.root,"BTCUSD",[self.sig],self.c,now=1000)
 def test_missing(self):
    self.assertEqual(self.run_freeze()["status"],"unavailable")
 def test_matching(self):
    self.save();r=self.run_freeze()
    self.assertEqual(r["status"],"research_advisory")
    self.assertEqual(r["matching_groups"][0]["sample_status"],"insufficient_sample")
    self.assertFalse(r["strategy_eligibility_changed"])
 def test_future(self):
    self.o["reference_end"]=1001;self.save()
    self.assertEqual(self.run_freeze()["status"],"unavailable")
 def test_stale(self):
    self.r["checked_at"]=300;self.save()
    self.assertEqual(self.run_freeze()["status"],"unavailable")
 def test_prompt(self):
    self.save();c=dict(self.c,paper_learning=self.run_freeze())
    e=dict(symbol="BTCUSD",as_of=1000,context=c,context_sha256=digest(c),mode="shadow",execution_authorized=False,new_signals=[self.sig],all_signals=[self.sig],conflicting_directions=False,event_id="new")
    q=prepare(e)
    self.assertIn("optional descriptive context",q["system"])
    self.assertFalse(q["execution_authorized"])
