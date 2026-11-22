"""Offline regression for M09 phase-specific financial evidence triage.

Uses test_fire_reconciliation's fully synthetic GET-only broker fixture.
No real network, private account files or order mutations.
"""
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradebot.fire_reconciliation_phase_probe import probe_single_recent_btc
from test_fire_reconciliation import Broker, START, NOW, PRESS


class M09PhaseProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="m09-probe-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.broker = Broker("BTCUSD")
        self.target_now = NOW + timedelta(minutes=1)
        self.original_request = self.broker._request

        def relaxed_broker(method, path, **kwargs):
            # Synthetic fixture is tied to NOW; the code under test must
            # request a 10+ minute-old receipt so that it can be audited.
            if path in ("/v2/fills", "/v2/wallet/transactions"):
                kwargs["params"] = dict(kwargs["params"])
                kwargs["params"]["end_time"] = int(NOW.timestamp()) * 1_000_000
            return self.original_request(method, path, **kwargs)
        self.broker._request = relaxed_broker
        self.inventory = {
            "entries_truncated": False,
            "entries": [
                {"symbol": "BTCUSD", "category": "locally_reported_flat",
                 "local_financial_report_present": False,
                 "created_at": START.isoformat(), "fire_id": PRESS},
            ],
        }
        self.receipt_rows = [(
            PRESS, START.isoformat(), NOW.isoformat(), "flat_verified",
            json.dumps(self.broker.trade),
        )]
        self.saved = {
            "parent": "100", "stop_loss_order": "102",
            "take_profit_order": "101",
        }
        self.inv = patch(
            "tradebot.fire_reconciliation_phase_probe.read_inventory",
            return_value=self.inventory)
        self.rows = patch(
            "tradebot.fire_reconciliation_phase_probe._read_rows",
            return_value=self.receipt_rows)
        self.local = patch(
            "tradebot.fire_reconciliation_phase_probe._saved",
            return_value=(self.saved, b"stable"))
        self.inv.start()
        self.rows.start()
        self.local.start()
        self.addCleanup(self.local.stop)
        self.addCleanup(self.rows.stop)
        self.addCleanup(self.inv.stop)

    def probe(self):
        return probe_single_recent_btc(
            self.broker, self.root, now=self.target_now)

    def test_completed_gets_are_only_provisional_not_trade_authority(self):
        report = self.probe()
        self.assertEqual(report["status"],
                         "provisional_read_only_financial_analysis_complete",
                         report)
        self.assertEqual(report["stage"], "complete")
        self.assertEqual(report["eligible_recent_btc_receipts"], 1)
        self.assertEqual(report["authenticated_order_gets"], 3)
        self.assertEqual(report["fill_count"], 4)
        self.assertEqual(report["wallet_posting_count"], 6)
        self.assertEqual(report["stages_passed"][-1],
                         "local_evidence_stability")
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertFalse(report["is_net_realized_pnl"])
        self.assertFalse(report["original_ledger_mutations"])
        self.assertFalse(report["temporary_ledger_mutations"])
        self.assertFalse(report["broker_order_mutations"])
        self.assertTrue(all(req[0] == "GET" for req in self.broker.calls))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_enabled_orders_client_rejected_before_any_get(self):
        self.broker.allow_orders = True
        report = self.probe()
        self.assertEqual(report["stage"], "preflight")
        self.assertEqual(report["reason"], "read_only_delta_demo_required")
        self.assertEqual(self.broker.calls, [])

    def test_wrong_broker_endpoint_rejected_before_gets(self):
        self.broker.base_url  # Actual DeltaDemo property is fixed
        class InvalidEndpoint:
            base_url = "https://api.delta.exchange"
            allow_orders = False
        report = probe_single_recent_btc(
            InvalidEndpoint(), self.root, now=self.target_now)
        self.assertEqual(report["reason"], "read_only_delta_demo_required")

    def test_no_local_bracket_receipts_does_not_call_broker(self):
        self.inventory["entries"].clear()
        report = self.probe()
        self.assertEqual(report["stage"], "receipt_selection")
        self.assertEqual(report["reason"], "no_recent_local_bracket_candidate")
        self.assertEqual(self.broker.calls, [])

    def test_product_fetch_failure_reports_phase_without_private_error(self):
        def fail(*args, **kwargs):
            raise RuntimeError("PRIVATE_BROKER_SECRET_SHOULD_NOT_APPEAR")
        self.broker._request = fail
        report = self.probe()
        self.assertEqual(report["stage"], "product")
        self.assertEqual(report["reason"], "broker_product_get_unavailable")
        self.assertNotIn("PRIVATE_BROKER_SECRET_SHOULD_NOT_APPEAR",
                         json.dumps(report))

    def test_parent_or_child_order_error_reports_order_stage(self):
        original = self.broker._request
        def fail_order(method, path, **kwargs):
            if path == "/v2/orders/102":
                raise RuntimeError("SECRET_SHOULD_NOT_APPEAR")
            return original(method, path, **kwargs)
        self.broker._request = fail_order
        report = self.probe()
        self.assertEqual(report["stage"], "orders")
        self.assertEqual(report["reason"], "broker_order_get_unavailable")
        self.assertEqual(report["authenticated_order_gets"], 1)
        self.assertNotIn("SECRET_SHOULD_NOT_APPEAR", json.dumps(report))

    def test_fill_history_failure_reports_fills_stage(self):
        original = self.broker._request
        def fail_fill(method, path, **kwargs):
            if path == "/v2/fills":
                raise RuntimeError("PRIVATE_FILL_ID")
            return original(method, path, **kwargs)
        self.broker._request = fail_fill
        report = self.probe()
        self.assertEqual(report["stage"], "fills")
        self.assertEqual(report["reason"], "broker_fill_history_unavailable")
        self.assertNotIn("PRIVATE_FILL_ID", json.dumps(report))

    def test_fill_schema_failure_is_separate_from_http_failure(self):
        self.broker.fills[0]["created_at"] = "bad-time"
        report = self.probe()
        self.assertEqual(report["stage"], "fill_normalization")
        self.assertEqual(report["reason"], "invalid_evidence_timestamp")

    def test_wallet_history_failure_reports_wallet_stage(self):
        original = self.broker._request
        def fail_wallet(method, path, **kwargs):
            if path == "/v2/wallet/transactions":
                raise RuntimeError("PRIVATE_WALLET_PAYLOAD")
            return original(method, path, **kwargs)
        self.broker._request = fail_wallet
        report = self.probe()
        self.assertEqual(report["stage"], "wallet_postings")
        self.assertEqual(report["reason"], "broker_wallet_history_unavailable")
        self.assertNotIn("PRIVATE_WALLET_PAYLOAD", json.dumps(report))

    def test_wallet_schema_failure_is_distinguished(self):
        self.broker.postings[0]["created_at"] = "bad-time"
        report = self.probe()
        self.assertEqual(report["stage"], "wallet_normalization")
        self.assertEqual(report["reason"], "invalid_evidence_timestamp")

    def test_accounting_mismatch_is_distinguished_without_reporting_money(self):
        self.broker.postings[-1]["amount"] = "-999"
        report = self.probe()
        self.assertEqual(report["stage"], "financial_analysis")
        self.assertEqual(report["reason"], "wallet_funding_mismatch")
        self.assertNotIn("-999", json.dumps(report))
        self.assertFalse(report["is_net_realized_pnl"])

    def test_changed_local_receipt_blocks_even_after_matching_broker_history(self):
        fingerprints = iter([(self.saved, b"stable"),
                             (self.saved, b"changed")])
        with patch(
            "tradebot.fire_reconciliation_phase_probe._saved",
            side_effect=lambda *a: next(fingerprints),
        ):
            report = self.probe()
        self.assertEqual(report["stage"], "local_evidence_stability")
        self.assertEqual(report["reason"], "original_btc_receipt_changed")
        self.assertFalse(report["trade_authorized"])


if __name__ == "__main__":
    unittest.main()
