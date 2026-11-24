import unittest
from datetime import datetime,timezone
from tradebot.m27_recovery_audit_v3 import project
NOW=1795524874
S="BTCUSD"
def reports():
    a=dict(mode="execution_account_diagnostic_only",checked_at=NOW,execution_authorized=False,markets={S:dict(identity_verified=True,flat_exposure_verified=True,observed_at=datetime.fromtimestamp(NOW,timezone.utc).isoformat())})
    m=dict(mode="read_only_position_monitor",checked_at=NOW,execution_authorized=False,markets={S:dict(current=dict(symbol=S,status="flat_observed",observed_us=NOW*1000000))})
    return a,m
class RecoveryTests(unittest.TestCase):
    def test_flat_never_authorizes(self):
        a,m=reports()
        r=project(S,a,m,0,now=NOW)
        self.assertEqual(r["alerts"],[])
        self.assertFalse(r["execution_authorized"])
        self.assertFalse(r["restart_recovery_commissioned"])
    def test_unresolved(self):
        a,m=reports()
        r=project(S,a,m,1,now=NOW)
        self.assertIn("unresolved_order_receipts",r["alerts"])
        self.assertFalse(r["retry_authorized"])
    def test_unknown_monitor_not_masked(self):
        a,m=reports()
        m["markets"][S]["current"]["status"]="unknown"
        r=project(S,a,m,0,now=NOW)
        self.assertTrue(r["direct_flatness_observed"])
        self.assertIn("monitor_unknown",r["alerts"])
    def test_stale(self):
        a,m=reports()
        r=project(S,a,m,None,now=NOW+91)
        self.assertFalse(r["direct_flatness_observed"])
        self.assertIn("receipt_audit_unavailable",r["alerts"])
    def test_unprotected(self):
        a,m=reports()
        m["markets"][S]["current"]["status"]="open_protection_unverified"
        self.assertIn("monitor_open_protection_unverified",project(S,a,m,0,now=NOW)["alerts"])

    def test_conflicting_inventory(self):
        for state in ("open_protection_unverified","open_protection_reported","flat_orders_present"):
            a,m=reports()
            m["markets"][S]["current"]["status"]=state
            r=project(S,a,m,0,now=NOW)
            self.assertEqual(r["exposure_state"],"conflicting_observations")
            self.assertIn("inventory_observations_disagree",r["alerts"])
            self.assertFalse(r["execution_authorized"])
    def test_exposure_distinctions(self):
        a,m=reports()
        self.assertEqual(project(S,a,m,0,now=NOW)["exposure_state"],"flat_corroborated")
        a["markets"][S]["flat_exposure_verified"]=False
        m["markets"][S]["current"]["status"]="open_protection_unverified"
        self.assertEqual(project(S,a,m,0,now=NOW)["exposure_state"],"open_reported")
        m["markets"][S]["current"]["status"]="unknown"
        self.assertEqual(project(S,a,m,0,now=NOW)["exposure_state"],"unresolved")
