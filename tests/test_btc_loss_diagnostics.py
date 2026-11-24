"""Offline BTC DEMO loss diagnostics; no broker, model or order interaction."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tradebot.btc_loss_diagnostics import analyze, accounting_contributor, LossDiagnosticError

AS_OF = 1795000000000000
P1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
P2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
P3 = "cccccccccccccccccccccccccccccccc"


def reconciliation(press, *, gross, fee, funding="0", at=AS_OF, verified=True,
                   fill_suffix=None):
    suffix = fill_suffix or press
    gross, fee, funding = (float(gross), float(fee), float(funding))
    obj = {
        "financial_reconciliation_status": "broker_reconciled" if verified
                                           else "awaiting_complete_broker_evidence",
        "reconciliation_version": "fire-reconciliation-v1",
        "reconciliation_reason": "matched_fills_and_wallet",
        "is_net_realized_pnl": verified,
        "funding_reconciled": verified,
        "gross_realized_pnl_usd": str(gross),
        "reconciled_fees_usd": str(fee),
        "funding_cashflow_usd": str(funding),
        "net_realized_pnl_usd": str(gross-fee+funding) if verified else None,
        "entry_at_us": at-120_000_000,
        "exit_at_us": at-60_000_000,
        "reconciliation_as_of_us": at,
        "matched_fill_ids": ["entry-"+suffix, "exit-"+suffix],
        "matched_posting_ids": ["cash-"+suffix, "fees-"+suffix],
    }
    return obj


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        self.finance=root/"reconciliation.sqlite"
        self.fire=root/"fire.sqlite"
        with sqlite3.connect(self.finance) as c:
            c.execute("CREATE TABLE reports("
                      "digest TEXT PRIMARY KEY, trade_key TEXT NOT NULL, "
                      "body TEXT NOT NULL)")
        with sqlite3.connect(self.fire) as c:
            c.execute("CREATE TABLE fire_requests("
                      "press TEXT PRIMARY KEY, status TEXT, result TEXT)")

    def report(self, press, value, *, tag=None):
        with sqlite3.connect(self.finance) as c:
            n=c.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
            c.execute("INSERT INTO reports VALUES (?,?,?)",
                      (tag or str(n), "BTCUSD:"+press, json.dumps(value)))

    def receipt(self, press, *, tier="exploratory_one", side="LONG",
                status="flat_verified", submitted=True, contracts=1):
        with sqlite3.connect(self.fire) as c:
            c.execute("INSERT INTO fire_requests VALUES (?,?,?)",
                      (press,status,json.dumps({
                          "orders_submitted": submitted,
                          "direction":side, "contracts":contracts,
                          "sizing_evidence": {"tier":tier}})))

    def test_no_financial_reports_cannot_claim_losses(self):
        out=analyze(self.finance,self.fire)
        self.assertEqual(out["status"],"awaiting_broker_reconciled_trades")
        self.assertEqual(out["verified_statistics"]["verified_trades"],0)
        self.assertEqual(out["loss_accounting_contributors"],{})
        self.assertFalse(out["account_pnl_verified"])
        self.assertEqual(out["ai_calls"],0)
        self.assertFalse(out["broker_mutations"])

    def test_price_fees_and_funding_contributors(self):
        self.report(P1,reconciliation(P1,gross="-4",fee=".50"))
        self.report(P2,reconciliation(P2,gross=".25",fee=".50"))
        self.report(P3,reconciliation(P3,gross="1",fee=".20",funding="-1.5"))
        self.receipt(P1,tier="exploratory_one",side="LONG")
        self.receipt(P2,tier="medium_two",side="SHORT",contracts=2)
        self.receipt(P3,tier="strong_three",side="LONG",contracts=3)
        out=analyze(self.finance,self.fire)
        self.assertEqual(out["status"],"verified_trades_available")
        self.assertEqual(out["verified_statistics"]["losses"],3)
        self.assertEqual(out["loss_accounting_contributors"],{
            "negative_gross_price_pnl":1,
            "fees_overwhelmed_nonnegative_gross":1,
            "funding_reversed_nonnegative_after_fee_pnl":1,
        })
        self.assertEqual(out["by_tier"]["medium_two"]["losses"],1)
        self.assertEqual(out["by_direction"]["SHORT"]["losses"],1)
        self.assertEqual(out["metadata_coverage"]["matched_fire_receipts"],3)
        self.assertEqual([r["tier"] for r in out["recent_verified_trade_summaries"]],
                         ["exploratory_one","medium_two","strong_three"])
        self.assertFalse(out["verified_statistics"]["sample_sufficient_for_strategy_change"])

    def test_dynamic_large_tier_remains_visible_in_loss_report(self):
        self.report(P1,reconciliation(P1,gross="-2",fee=".4"))
        self.receipt(P1,tier="strong_dynamic",side="SHORT",contracts=5)
        out=analyze(self.finance,self.fire)
        self.assertEqual(out["by_tier"]["strong_dynamic"]["losses"],1)
        self.assertEqual(out["recent_verified_trade_summaries"][0]["contracts_recorded"],5)

    def test_latest_unverified_replaces_older_verified(self):
        old=reconciliation(P1,gross="-2",fee=".2")
        self.report(P1,old)
        revised=reconciliation(P1,gross="-2",fee=".2",at=AS_OF+600_000_000,
                               verified=False)
        self.report(P1,revised)
        self.receipt(P1)
        r=analyze(self.finance,self.fire)
        self.assertEqual(r["verified_statistics"]["verified_trades"],0)
        self.assertEqual(r["unverified_report_reasons"]["not_fully_broker_reconciled"],1)

    def test_conflicting_latest_reports_are_excluded(self):
        a=reconciliation(P1,gross="-2",fee=".2")
        b=reconciliation(P1,gross="-2",fee=".4")
        self.report(P1,a)
        self.report(P1,b)
        self.receipt(P1)
        r=analyze(self.finance,self.fire)
        self.assertEqual(r["verified_statistics"]["verified_trades"],0)
        self.assertEqual(r["unverified_report_reasons"]["conflicting_latest_report"],1)

    def test_shared_fill_id_cannot_double_count(self):
        self.report(P1,reconciliation(P1,gross="-2",fee=".2",fill_suffix="same"))
        self.report(P2,reconciliation(P2,gross="3",fee=".2",fill_suffix="same"))
        self.receipt(P1)
        self.receipt(P2)
        r=analyze(self.finance,self.fire)
        self.assertEqual(r["verified_statistics"]["verified_trades"],0)
        self.assertEqual(r["unverified_report_reasons"]["shared_broker_evidence"],2)

    def test_missing_or_unsafe_fire_receipt_is_not_forced_into_tier(self):
        self.report(P1,reconciliation(P1,gross="-2",fee=".2"))
        self.receipt(P1,status="exposure_unknown",submitted=True)
        r=analyze(self.finance,self.fire)
        self.assertEqual(r["verified_statistics"]["losses"],1)
        self.assertEqual(r["metadata_coverage"]["missing_or_ambiguous_fire_receipts"],1)
        self.assertEqual(r["by_tier"]["unknown"]["losses"],1)
        self.assertEqual(r["by_direction"]["unknown"]["losses"],1)

    def test_missing_finance_database_is_explicit(self):
        self.finance.unlink()
        r=analyze(self.finance,self.fire)
        self.assertEqual(r["status"],"financial_reconciliation_ledger_missing")
        self.assertEqual(r["verified_statistics"]["verified_trades"],0)

    def test_symlinked_financial_ledger_is_rejected(self):
        other=self.finance.parent/"replay.db"
        self.finance.rename(other)
        self.finance.symlink_to(other)
        with self.assertRaises(LossDiagnosticError):
            analyze(self.finance,self.fire)

    def test_invalid_report_limits_are_rejected(self):
        with self.assertRaises(LossDiagnosticError):
            analyze(self.finance,self.fire,max_reports=0)
        with self.assertRaises(LossDiagnosticError):
            analyze(self.finance,self.fire,recent_limit=101)

    def test_accounting_contribution_not_strategy_causation(self):
        self.assertEqual(accounting_contributor(0,1,0,-1),
                         "fees_overwhelmed_nonnegative_gross")
        self.assertEqual(accounting_contributor(3,1,-3,-1),
                         "funding_reversed_nonnegative_after_fee_pnl")
        self.assertEqual(accounting_contributor(-4,0,0,-4),
                         "negative_gross_price_pnl")
        self.assertEqual(accounting_contributor(4,1,0,3),"not_a_net_loss")


if __name__ == "__main__":
    unittest.main()
