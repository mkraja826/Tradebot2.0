import unittest
from tempfile import TemporaryDirectory
from datetime import datetime,timezone
from pathlib import Path
from tradebot.deployment_readiness_v3 import checkpoint_status,finalize
NOW=1800000000
class DeploymentReadinessTests(unittest.TestCase):
    def test_checkpoint_fresh_and_stale(self):
        raw=dict(as_of=datetime.fromtimestamp(NOW,timezone.utc).isoformat(),mode="read_only",
                 status="monitoring_degraded",blocking_conditions=["equity_loss_limit_breached"],checkpoint_prerequisites_met=False)
        r=checkpoint_status(raw,NOW)
        self.assertFalse(r["prerequisites_met"]); self.assertFalse(r["execution_authorized"])
        self.assertEqual(r["blocking_conditions"],["equity_loss_limit_breached"])
        self.assertEqual(checkpoint_status(raw,NOW+91)["status"],"unavailable")
        self.assertEqual(checkpoint_status({},NOW)["status"],"unavailable")
    def test_diagnostic_never_authorizes(self):
        with TemporaryDirectory() as d:
            r=finalize(d,reader=lambda:{"BTCUSD":{"signed_account_verified":True,"halted":False,"status":"partial"}},
                checkpoint_reader=lambda:{"as_of":datetime.fromtimestamp(NOW,timezone.utc).isoformat(),"mode":"read_only",
                    "status":"healthy","blocking_conditions":[],"checkpoint_prerequisites_met":True},clock=lambda:NOW)
            self.assertFalse(r["execution_authorized"])
            self.assertFalse(r["live_ai_enabled"])
            self.assertTrue(r["checkpoint"]["prerequisites_met"])
            self.assertEqual(r["markets"]["BTCUSD"]["status"],"shadow_only")
            self.assertFalse(r["shadow_worker_fresh"])
            self.assertTrue((Path(d)/"deployment-readiness-v3.json").exists())
