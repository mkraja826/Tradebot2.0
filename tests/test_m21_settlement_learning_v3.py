import unittest
from tradebot.m21_settlement_learning_v3 import project
class SettlementTests(unittest.TestCase):
 def fixture(self):
    row=dict(symbol="BTCUSD",is_net_realized_pnl=True,reconciliation_status="broker_reconciled",net_realized_pnl_usd="7",gross_realized_pnl_usd="10",fees_usd="2",funding_usd="-1")
    return dict(symbol="BTCUSD",status="complete_broker_window",source="signed_delta_india_demo_readonly",as_of="2026-11-24T10:40:00+00:00",window_days=7,fire_trade_count_in_window=2,broker_reconciled_closed_trades=1,unverified_or_open_trades=1,signed_fill_count=2,signed_wallet_posting_count=5,history_truncated=False,trade_rows=[row,dict(symbol="BTCUSD",is_net_realized_pnl=False,reason="missing_broker_funding_total")])
 def test_verified_only(self):
    r=project("BTCUSD",self.fixture());self.assertEqual(r["verified_subset_net_usd"],"7");self.assertEqual(r["verified_wins"],1);self.assertFalse(r["execution_authorized"]);self.assertIsNone(r["stop_target_effectiveness"])
 def test_incomplete(self):
    f=self.fixture();f["history_truncated"]=True;r=project("BTCUSD",f);self.assertIsNone(r["verified_subset_net_usd"])
 def test_mismatch(self):
    f=self.fixture();f["trade_rows"][0]["net_realized_pnl_usd"]="10"
    with self.assertRaises(ValueError):project("BTCUSD",f)
 def test_none(self):
    f=self.fixture();f["trade_rows"]=f["trade_rows"][1:];f["fire_trade_count_in_window"]=1;f["broker_reconciled_closed_trades"]=0
    self.assertIsNone(project("BTCUSD",f)["verified_subset_net_usd"])
 def test_full_research_rows(self):
    f=self.fixture();f["trade_rows"]=[dict(symbol="BTCUSD",is_net_realized_pnl=False,reason="unattributed_wallet_posting",wallet_timing_evidence=dict(status="timing_counts_only",nonowned_during_position=0,nonowned_after_flat_fill=1,after_flat_without_order_or_fill_ref=1)) for _ in range(42)]
    f.update(fire_trade_count_in_window=42,broker_reconciled_closed_trades=0,unverified_or_open_trades=42)
    r=project("BTCUSD",f)
    self.assertEqual(r["status"],"complete_broker_window")
    self.assertEqual(r["wallet_attribution_diagnostics"]["receipts_with_nonowned_after_flat_fill"],42)
    self.assertIsNone(r["verified_subset_net_usd"])
    f["trade_rows"]=f["trade_rows"][:40]
    self.assertEqual(project("BTCUSD",f)["status"],"incomplete_receipt_coverage")
