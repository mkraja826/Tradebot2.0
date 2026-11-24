import unittest
from tradebot.m21_settlement_archive_v3 import project
class ArchiveTests(unittest.TestCase):
 def fixture(self):
    a=dict(status="complete_broker_window",fire_receipts=2,verified_closed=0,unverified_or_open=2,unverified_reasons=dict(broker_order_not_submitted=1,unattributed_wallet_posting=1),wallet_attribution_diagnostics=dict(receipts_with_after_flat_without_order_or_fill_ref=1))
    return dict(mode="settlement_learning_research_only",execution_authorized=False,orders_submitted=0,paid_ai_requests=0,parent_equity_included=False,checked_at=1000,markets={"BTCUSD":dict(a),"XAUTUSD":dict(a)})
 def test_research_only(self):
    r=project(self.fixture(),1001)
    self.assertEqual(r["markets"]["BTCUSD"]["unresolved"],1)
    self.assertFalse(r["markets"]["BTCUSD"]["verified_learning_available"])
    self.assertFalse(r["strategy_eligibility_changed"])
 def test_stale(self):
    with self.assertRaises(ValueError):project(self.fixture(),1601)
 def test_incomplete(self):
    f=self.fixture();f["markets"]["BTCUSD"]["status"]="incomplete_receipt_coverage"
    with self.assertRaises(ValueError):project(f,1001)
 def test_counts(self):
    f=self.fixture();f["markets"]["BTCUSD"]["verified_closed"]=1
    with self.assertRaises(ValueError):project(f,1001)
