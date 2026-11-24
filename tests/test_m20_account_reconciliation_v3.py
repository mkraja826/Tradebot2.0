import unittest
from tradebot.m20_account_reconciliation_v3 import project
class ReconciliationTests(unittest.TestCase):
    def test_new_connection_does_not_clear_legacy(self):
        owner={"status":"fresh_local_report","markets":{"BTCUSD":{"account_evidence_fresh":True}}}
        legacy={"BTCUSD":{"signed_account_verified":False,"halted":True}}
        r=project(owner,legacy,{"prerequisites_met":False},now=1)
        b=r["markets"]["BTCUSD"]
        self.assertTrue(b["connection_discrepancy"])
        self.assertIn("halt_active_or_unknown",b["blockers"])
        self.assertIn("legacy_checkpoint_unmet_or_unknown",b["blockers"])
        self.assertFalse(b["autonomous_trading_ready"])
        self.assertFalse(r["execution_authorized"])
    def test_unknown_is_not_ready(self):
        r=project({}, {}, {},now=1)
        for b in r["markets"].values():
            self.assertFalse(b["new_monitor_fresh"])
            self.assertIn("halt_active_or_unknown",b["blockers"])
    def test_healthy_is_not_execution_authorization(self):
        owner={"status":"fresh_local_report","markets":{"BTCUSD":{"account_evidence_fresh":True}}}
        b=project(owner,{"BTCUSD":{"signed_account_verified":True,"halted":False}},{"prerequisites_met":True},now=1)["markets"]["BTCUSD"]
        self.assertFalse(b["autonomous_trading_ready"])
        self.assertIn("broker_execution_uncommissioned",b["blockers"])
