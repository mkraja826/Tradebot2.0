"""Offline regression coverage for broker-reconciled subset performance.

All fixtures represent already-reconciled, append-only local reports. No
trade, network, paid AI, account, or strategy interactions are permitted.
"""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tradebot.fire_performance import read_performance, PerformanceEvidenceError

BASE = 1795000000000000


def report(amount, *, cutoff=BASE + 900_000_000, exit_at=BASE + 120_000_000,
           tag="a", verified=True):
    value = str(amount)
    if not verified:
        return {"financial_reconciliation_status":"awaiting_complete_broker_evidence",
                "is_net_realized_pnl":False, "reconciliation_reason":"wallet_funding_mismatch",
                "reconciliation_as_of_us":cutoff,
                "net_realized_pnl_usd":None}
    return {
        "financial_reconciliation_status":"broker_reconciled",
        "is_net_realized_pnl":True,
        "funding_reconciled":True,
        "reconciliation_version":"fire-reconciliation-v1",
        "reconciliation_reason":"matched_fills_and_wallet",
        "net_realized_pnl_usd":value,
        "gross_realized_pnl_usd":value,
        "reconciled_fees_usd":"0",
        "funding_cashflow_usd":"0",
        "entry_at_us":exit_at-60_000_000,
        "exit_at_us":exit_at,
        "reconciliation_as_of_us":cutoff,
        "matched_fill_ids":["entry-"+tag,"exit-"+tag],
        "matched_posting_ids":["cash-"+tag,"fee-"+tag],
    }


class FirePerformanceTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"fire-reconciliation.sqlite"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE reports("
                       "digest TEXT PRIMARY KEY, trade_key TEXT NOT NULL, body TEXT NOT NULL)")

    def add(self, symbol, fireid, data, marker=None):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO reports VALUES (?,?,?)",
                       (marker or symbol+":"+fireid+":"+str(db.execute(
                           "SELECT count(*) FROM reports").fetchone()[0]),
                        symbol+":"+fireid,json.dumps(data,sort_keys=True)))

    def test_zero_reports_not_fabricated_as_profitable(self):
        summary=read_performance(self.path)
        self.assertIsNone(summary["verified_subset_net_usd"])
        self.assertEqual(summary["verified_trades"],0)
        self.assertIsNone(summary["win_rate_pct"])
        self.assertIsNone(summary["verified_subset_profit_factor"])
        self.assertFalse(summary["is_account_realized_pnl"])

    def test_absent_database_cannot_generate_account_claim(self):
        missing=self.path.with_name("absent.sqlite")
        summary=read_performance(missing)
        self.assertEqual(summary["evidence_status"],"ledger_missing")
        self.assertFalse(missing.exists())
        self.assertEqual(summary["verified_trades"],0)

    def test_two_markets_one_win_one_loss_and_zero_dedupe(self):
        self.add("BTCUSD","a"*32,report("6",tag="btc",exit_at=BASE+120_000_000))
        self.add("XAUTUSD","b"*32,report("-2",tag="gold",exit_at=BASE+130_000_000))
        stats=read_performance(self.path)
        self.assertEqual(stats["total_reviewed_trades"],2)
        self.assertEqual(stats["verified_trades"],2)
        self.assertEqual(stats["verified_subset_net_usd"],"4")
        self.assertEqual(stats["win_rate_pct"],"50.00")
        self.assertEqual(stats["verified_subset_expectancy_usd_per_trade"],"2")
        self.assertEqual(stats["verified_subset_profit_factor"],"3")
        self.assertEqual(stats["verified_subset_trade_sequence_max_drawdown_usd"],"2")
        self.assertEqual(stats["by_market"]["XAUTUSD"]["verified_subset_net_usd"],"-2")
        self.assertFalse(stats["is_account_drawdown"])

    def test_breakeven_and_all_winners_do_not_invent_infinite_profit_factor(self):
        self.add("BTCUSD","a"*32,report("2",tag="1"))
        self.add("BTCUSD","b"*32,report("0",tag="2"))
        stats=read_performance(self.path)
        self.assertEqual(stats["breakeven"],1)
        self.assertIsNone(stats["verified_subset_profit_factor"])
        self.assertEqual(stats["profit_factor_note"],"undefined_without_verified_losses")

    def test_later_failed_reconciliation_overrules_prior_verified(self):
        key="a"*32
        self.add("BTCUSD",key,report("10",tag="a",cutoff=BASE+900_000_000))
        self.add("BTCUSD",key,report(None,verified=False,cutoff=BASE+950_000_000))
        stats=read_performance(self.path)
        self.assertEqual(stats["verified_trades"],0)
        self.assertEqual(stats["unverified_trades"],1)
        self.assertIsNone(stats["verified_subset_net_usd"])
        self.assertEqual(stats["unverified_reasons"],{"wallet_funding_mismatch":1})

    def test_same_report_repeated_does_not_increase_sample_count(self):
        key="a"*32
        data=report("10",tag="a")
        self.add("BTCUSD",key,data)
        self.add("BTCUSD",key,data)
        stats=read_performance(self.path)
        self.assertEqual(stats["verified_trades"],1)
        self.assertEqual(stats["verified_subset_net_usd"],"10")

    def test_conflicting_latest_same_cutoff_becomes_unverified(self):
        key="a"*32
        self.add("BTCUSD",key,report("2",tag="a"))
        self.add("BTCUSD",key,report("8",tag="a"))
        stats=read_performance(self.path)
        self.assertEqual(stats["verified_trades"],0)
        self.assertEqual(stats["unverified_reasons"],{"conflicting_latest_reports":1})

    def test_unsequenced_new_report_blocks_reusing_old_verified_outcome(self):
        key="a"*32
        self.add("BTCUSD",key,report("6",tag="a"))
        self.add("BTCUSD",key,{"is_net_realized_pnl":False,
                              "reconciliation_reason":"broker_unavailable"})
        stats=read_performance(self.path)
        self.assertEqual(stats["verified_trades"],0)
        self.assertEqual(stats["unverified_reasons"],{"unsequenced_or_unverified_report":1})

    def test_unverified_sample_is_not_hidden(self):
        self.add("BTCUSD","a"*32,report("2",tag="a"))
        self.add("XAUTUSD","b"*32,report(None,verified=False,tag="b"))
        stats=read_performance(self.path)
        self.assertEqual(stats["verified_trades"],1)
        self.assertEqual(stats["unverified_trades"],1)
        self.assertFalse(stats["all_reviewed_trades_verified"])
        self.assertEqual(stats["verified_subset_net_usd"],"2")
        self.assertEqual(stats["by_market"]["XAUTUSD"]["verified_trades"],0)

    def test_incomplete_economics_or_invalid_timestamp_cannot_be_counted(self):
        for n,change in enumerate((
            {"funding_reconciled":False},
            {"net_realized_pnl_usd":"NaN"},
            {"net_realized_pnl_usd":"99"},
            {"exit_at_us":BASE+950_000_000},
            {"matched_fill_ids":[]},
            {"is_net_realized_pnl":"true"},
        )):
            data=report("3",tag=str(n))
            data.update(change)
            self.add("BTCUSD",str(n)*32,data)
        stats=read_performance(self.path)
        self.assertEqual(stats["verified_trades"],0)
        self.assertEqual(stats["unverified_trades"],6)

    def test_reused_broker_evidence_across_trades_fails_closed(self):
        self.add("BTCUSD","a"*32,report("1",tag="same"))
        self.add("XAUTUSD","b"*32,report("4",tag="same"))
        with self.assertRaisesRegex(PerformanceEvidenceError,"multiple trades"):
            read_performance(self.path)

    def test_corrupted_report_db_fails_closed(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO reports VALUES (?,?,?)",
                       ("bad","BTCUSD:"+("a"*32),"{not json"))
        with self.assertRaisesRegex(PerformanceEvidenceError,"Malformed"):
            read_performance(self.path)

    def test_malformed_trade_key_fails_closed(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO reports VALUES (?,?,?)",
                       ("bad","UNKNOWN:abc",json.dumps(report("5"))))
        with self.assertRaisesRegex(PerformanceEvidenceError,"ownership"):
            read_performance(self.path)


if __name__=="__main__":
    unittest.main()
