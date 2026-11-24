import unittest
from tradebot.m15_autonomous_readiness_v3 import consolidate,MODES
NOW=1800000000
class AutonomousReadinessTests(unittest.TestCase):
    def reports(self):
        r={k:dict(mode=v,checked_at=NOW,execution_authorized=False,paid_ai_requests=0,orders_submitted=0,markets={}) for k,v in MODES.items()}
        for s in ("BTCUSD","XAUTUSD"):
            r["commissioning"]["markets"][s]={"product":"ready"}
            r["account"]["markets"][s]={"dashboard":{"identity_verified":True,"status":"partial","halted":False},"signed_client_status":"not_provisioned"}
            r["provider"]["markets"][s]={"compatibility":{"status":"passed"}}
            r["decision"]["markets"][s]={"fixture":{"status":"passed","actions":["WAIT","LONG","SHORT"]}}
            r["execution"]["markets"][s]={"fixtures":[dict(side=side,status="passed",broker_verified=False) for side in ("LONG","SHORT")]}
        r["commissioning"]["research_checks_passed"]=True
        r["commissioning"]["checkpoint"]={"prerequisites_met":False,"blocking_conditions":["equity_loss_limit_breached"]}
        return r
    def test_offline_is_not_authority(self):
        x=consolidate(self.reports(),now=NOW)
        self.assertTrue(x["research_checks_passed"])
        self.assertFalse(x["execution_authorized"])
        self.assertFalse(x["checkpoint"]["prerequisites_met"])
        for m in x["markets"].values():
            self.assertTrue(m["offline_pipeline_passed"])
            self.assertFalse(m["autonomous_trading_ready"])
    def test_stale_or_authorizing_report(self):
        r=self.reports();r["execution"]["checked_at"]=NOW-151
        r["provider"]["execution_authorized"]=True
        x=consolidate(r,now=NOW)
        self.assertFalse(x["report_freshness"]["execution"])
        self.assertFalse(x["report_freshness"]["provider"])
        self.assertFalse(x["markets"]["BTCUSD"]["offline_pipeline_passed"])
        self.assertFalse(consolidate({},now=NOW)["research_checks_passed"])
