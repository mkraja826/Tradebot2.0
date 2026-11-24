import unittest,json
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.m15_commissioning_v3 import matrix,evidence
NOW=1800000000
class M15Tests(unittest.TestCase):
    def test_readiness_never_authorizes(self):
        with TemporaryDirectory() as d:
            dep={"research_checks_passed":True,"checkpoint":{"prerequisites_met":True},"markets":{"BTCUSD":{"identity_observed":True,"halted":False,"account_context":"partial"}}}
            con={"markets":{"BTCUSD":{"product":"ready","wire_prepared":True}}}
            r=matrix(d,dep,con,now=NOW)
            self.assertFalse(r["execution_authorized"])
            self.assertFalse(r["live_ai_enabled"])
            self.assertEqual(r["markets"]["BTCUSD"]["commissioning_status"],"not_ready")
            self.assertFalse(r["markets"]["BTCUSD"]["provider_authentication_verified"])
            self.assertFalse(r["markets"]["XAUTUSD"]["account_identity_observed"])
    def test_evidence_freshness(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"decision-quality-v3.json"
            for t,state in ((NOW,"fresh"),(NOW-661,"stale"),(NOW+1,"unavailable")):
                p.write_text(json.dumps({"mode":"synthetic_decision_quality","checked_at":t,"execution_authorized":False}))
                self.assertEqual(evidence(d,"decision_quality",NOW)[0]["status"],state)
            p.write_text(json.dumps({"mode":"synthetic_decision_quality","checked_at":NOW,"execution_authorized":True}))
            self.assertEqual(evidence(d,"decision_quality",NOW)[0]["status"],"unavailable")
