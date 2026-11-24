from datetime import datetime,timezone
import unittest
from tradebot.m26_execution_review_v3 import project
NOW=1795523060
def report(s="BTCUSD"):
    return dict(mode="execution_account_diagnostic_only",checked_at=NOW,orders_submitted=0,execution_authorized=False,markets={s:dict(observed_at=datetime.fromtimestamp(NOW,timezone.utc).isoformat(),identity_verified=True,flat_exposure_verified=True,leverage_evidence={"within_existing_20x_ceiling":True})})
class ReviewTests(unittest.TestCase):
    def test_preserves_breach(self):
        for s in ("BTCUSD","XAUTUSD"):
            r=project(s,report(s),{"prerequisites_met":False,"blocking_conditions":["equity_loss_limit_breached"]},{"weekly_checkpoint":"missed_window"},now=NOW)
            self.assertEqual(r["checks"]["existing_equity_release"],"blocked")
            self.assertEqual(r["existing_release_blockers"],["equity_loss_limit_breached"])
            self.assertFalse(r["execution_authorized"])
    def test_stale_or_wrong_market(self):
        for a,t in ((report(),NOW+91),(report("XAUTUSD"),NOW),({},NOW)):
            r=project("BTCUSD",a,{}, {},now=t)
            self.assertEqual(r["checks"]["account_identity"],"unverified")
            self.assertIn("checkpoint_unverified",r["existing_release_blockers"])
    def test_malformed_or_inconsistent_account_evidence(self):
        for leverage in (None,[],"bad",True):
            a=report();a["markets"]["BTCUSD"]["leverage_evidence"]=leverage
            r=project("BTCUSD",a,{}, {},now=NOW)
            self.assertEqual(r["checks"]["configured_leverage"],"unverified_or_outside_ceiling")
            self.assertFalse(r["execution_authorized"])
        a=report();a["markets"]["BTCUSD"]["identity_verified"]=False
        r=project("BTCUSD",a,{}, {},now=NOW)
        self.assertEqual(r["checks"]["account_flatness"],"unverified")
        self.assertEqual(r["checks"]["configured_leverage"],"unverified_or_outside_ceiling")
    def test_no_approval_even_healthy(self):
        r=project("BTCUSD",report(),{"prerequisites_met":True},{},now=NOW)
        self.assertEqual(r["checks"]["account_identity"],"observed")
        self.assertFalse(r["execution_authorized"])
        self.assertFalse(r["policy_deployed"])
