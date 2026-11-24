import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.synthetic_lifecycle_v3 import LifecycleLedger,fixture_receipt,fixture_protections
from tradebot.m27_restart_research_v3 import inspect
from test_m23_limit_lifecycle_v3 import preview

class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"fixture.sqlite"
        self.p=preview();self.p["entry"]["kind"]="MARKET"
        self.ledger=LifecycleLedger(self.path);self.ledger.reserve(self.p)
    def check(self,status):
        r=inspect(self.path,self.p)
        self.assertEqual(r["status"],status)
        self.assertFalse(r["execution_authorized"])
        self.assertFalse(r["retry_authorized"])
        self.assertFalse(r["settlement_verified"])
        return r
    def test_reserved_restart(self):
        self.check("unresolved_requires_reconciliation")
        self.assertEqual(LifecycleLedger(self.path).reserve(self.p),"already_reserved")
    def test_partial_and_unknown(self):
        self.ledger.observe(self.p,fixture_receipt(self.p,1,"open"),fixture_protections(self.p,1),stamp=1)
        self.check("fixture_protection_reported")
        self.ledger.observe(self.p,None,[],stamp=2)
        self.assertEqual(self.check("unresolved_requires_reconciliation")["prior_known_filled_contracts"],1)
    def test_missing_protection(self):
        self.ledger.observe(self.p,fixture_receipt(self.p,3,"closed"),[],stamp=1)
        self.check("fixture_protection_missing")
    def test_wrong_parent(self):
        b=fixture_protections(self.p,3);b[0]["parent_client_id"]="other"
        self.ledger.observe(self.p,fixture_receipt(self.p,3,"closed"),b,stamp=1)
        self.check("fixture_protection_missing")
    def test_rejected(self):
        self.ledger.observe(self.p,fixture_receipt(self.p,0,"rejected"),[],stamp=1)
        self.check("fixture_rejected_observed")
    def test_conflicting_preview(self):
        self.p["entry"]["contracts"]=4
        self.check("conflicting_preview")
    def test_missing_database(self):
        self.assertEqual(inspect(self.path.with_name("missing.sqlite"),self.p)["status"],"evidence_unavailable")
        self.assertFalse(self.path.with_name("missing.sqlite").exists())
