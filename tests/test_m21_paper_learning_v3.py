import unittest
from tradebot.m21_paper_learning_v3 import link,summarize
class PaperLearningTests(unittest.TestCase):
 def fixture(self):
    e=dict(event_id="x",symbol="BTCUSD",model_if_enabled="GPT-6.1 Sol",as_of=100)
    r=dict(event_id="x",symbol="BTCUSD",request_sha256="h",model="tb-gpt-6-1-sol",status="validated_paper_proposal",execution_authorized=False,orders_submitted=0,account_basis="hypothetical",checked_at=110,decision=dict(event_id="x",symbol="BTCUSD",action="WAIT",plan=None))
    return e,r
 def test_valid(self):
    e,r=self.fixture()
    self.assertEqual(link(e,r,"x","BTCUSD",105,"h",120)["action"],"WAIT")
 def test_invalid(self):
    for k,v in (("model","wrong"),("execution_authorized",True),("status","transport_outcome_unknown"),("checked_at",251),("request_sha256","different"),("orders_submitted",1)):
        e,r=self.fixture();r[k]=v
        with self.assertRaises(ValueError):link(e,r,"x","BTCUSD",105,"h",300)
 def test_signal_not_pnl(self):
    records=[dict(symbol="BTCUSD",action="WAIT",signal_paths=[dict(event_id="x",horizon_minutes=15,status="observed",directional_return_pct=1),dict(event_id="x",horizon_minutes=15,status="observed",directional_return_pct=-2),dict(event_id="x",horizon_minutes=60,status="pending")])]
    r=summarize(records)
    self.assertEqual(r[0]["mean_signal_direction_return_pct"],-.5)
    self.assertEqual(r[0]["distinct_observed_events"],1)
    self.assertFalse(r[0]["actual_trade_outcome"])
    self.assertIsNone(r[1]["mean_signal_direction_return_pct"])
