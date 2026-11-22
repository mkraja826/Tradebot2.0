"""Offline regression for M09 phase-specific financial evidence triage.

Uses test_fire_reconciliation's fully synthetic GET-only broker fixture.
No real network, private account files or order mutations.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradebot.fire_reconciliation_phase_probe import probe_single_recent_btc
from test_fire_reconciliation import Broker, START, NOW, PRESS, BASE


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

    def probe(self, *, now=None, fire_id=None):
        return probe_single_recent_btc(
            self.broker, self.root, now=now or self.target_now, fire_id=fire_id)

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
        self.assertTrue(report["cashflow_and_commission_consistency_proven_in_memory"])
        self.assertFalse(report["original_ledger_mutations"])
        self.assertFalse(report["temporary_ledger_mutations"])
        self.assertFalse(report["broker_order_mutations"])
        self.assertTrue(all(req[0] == "GET" for req in self.broker.calls))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_broker_funding_retains_cash_fee_proof_but_no_net_pnl(self):
        del self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"]
        report = self.probe()
        self.assertEqual(report["stage"], "financial_analysis")
        self.assertEqual(report["reason"], "missing_broker_funding_total")
        self.assertTrue(report["cashflow_and_commission_consistency_proven_in_memory"])
        self.assertFalse(report["is_net_realized_pnl"])
        self.assertFalse(report["funding_reconciled"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_funding_with_invalid_fee_is_never_mislabeled_as_verified(self):
        del self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"]
        self.broker.postings[0]["amount"] = "99"
        report = self.probe()
        self.assertEqual(report["reason"], "wallet_commission_mismatch")
        self.assertFalse(report["cashflow_and_commission_consistency_proven_in_memory"])
        self.assertFalse(report["is_net_realized_pnl"])

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


    def test_delayed_unreferenced_funding_is_classified_not_waived(self):
        self.broker.postings[-1]["created_at"] = BASE + 100_000_000
        report = self.probe()
        self.assertEqual(report["reason"], "unattributed_wallet_posting")
        self.assertEqual(report["stage"], "financial_analysis")
        hints = report["unattributed_wallet_posting_diagnostic"]
        self.assertEqual(hints["count"], 1)
        self.assertEqual(hints["examples"], [{
            "product_scope": "same_product",
            "timing": "after_last_fill",
            "order_reference": "absent",
            "fill_reference": "absent",
            "posting_kind": "funding",
        }])
        self.assertFalse(hints["examples_truncated"])
        self.assertFalse(report["cashflow_and_commission_consistency_proven_in_memory"])
        self.assertFalse(report["funding_reconciled"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertTrue(all(req[0] == "GET" for req in self.broker.calls))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_account_unscoped_posting_is_classified_without_balance_or_id(self):
        unknown = self.broker.posting("PRIVATE-POSTING-ID", "commission", "-0.1", 90)
        unknown["product_id"] = 0
        unknown["balance"] = "PRIVATE-BALANCE-123"
        self.broker.postings.append(unknown)
        report = self.probe()
        self.assertEqual(report["reason"], "unattributed_wallet_posting")
        hints = report["unattributed_wallet_posting_diagnostic"]
        self.assertEqual(hints["count"], 1)
        self.assertEqual(hints["examples"][0]["product_scope"], "account_unscoped")
        self.assertEqual(hints["examples"][0]["posting_kind"], "commission")
        self.assertNotIn("PRIVATE-", json.dumps(report))
        self.assertNotIn("-0.1", json.dumps(report))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_multiple_unattributed_postings_show_bounded_categories(self):
        for n in range(7):
            unknown = self.broker.posting(f"unscoped-{n}", "commission", "-0.1", 90 + n)
            unknown["product_id"] = None
            self.broker.postings.append(unknown)
        report = self.probe()
        self.assertEqual(report["reason"], "unattributed_wallet_posting")
        hints = report["unattributed_wallet_posting_diagnostic"]
        self.assertEqual(hints["count"], 7)
        self.assertEqual(len(hints["examples"]), 5)
        self.assertEqual(len(hints["amount_consistency_clues"]), 5)
        self.assertTrue(hints["examples_truncated"])
        self.assertFalse(report["trade_authorized"])

    def test_post_close_commission_fill_uuid_links_only_real_signed_fill(self):
        # Delta DEMO wallet commissions can include meta_data.fill_uuid
        # instead of meta_data.fill_id. The UUID must match a signed fill
        # selected through the original owned broker order.
        uuid = "c7b384f4-3d1c-4a19-b7fe-12c6b2b1040d"
        self.broker.fills[3]["id"] = uuid
        late = self.broker.postings[3]
        late["meta_data"] = {"fill_uuid": uuid}
        late["created_at"] = BASE + 92_000_000
        result = self.probe()
        self.assertEqual(result["status"],
                         "provisional_read_only_financial_analysis_complete",
                         result)
        self.assertFalse(result["is_net_realized_pnl"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["trade_authorized"])
        self.assertTrue(result["cashflow_and_commission_consistency_proven_in_memory"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unknown_post_close_commission_fill_uuid_does_not_create_ownership(self):
        late = self.broker.postings[3]
        late["meta_data"] = {
            "fill_uuid": "4d777777-2222-4444-aaaa-555555555555"
        }
        late["created_at"] = BASE + 92_000_000
        result = self.probe()
        self.assertEqual(result["reason"], "unattributed_wallet_posting")
        self.assertFalse(result["is_net_realized_pnl"])
        self.assertFalse(result["cashflow_and_commission_consistency_proven_in_memory"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_malformed_or_conflicting_wallet_uuid_never_claims_fill_link(self):
        fee = self.broker.postings[3]
        for metadata, reason in (
            ({"fill_uuid": "not-a-real-uuid"}, "invalid_wallet_fill_uuid"),
            ({"fill_uuid": "c7b384f4-3d1c-4a19-b7fe-12c6b2b1040d",
              "fill_id": "different-fill"}, "conflicting_posting_reference"),
        ):
            with self.subTest(meta=metadata):
                fee["meta_data"] = metadata
                report = self.probe()
                self.assertEqual(report["stage"], "wallet_normalization")
                self.assertEqual(report["reason"], reason)
                self.assertFalse(report["trade_authorized"])

    def test_cashflow_cannot_inherit_fill_uuid_as_ownership(self):
        cash = self.broker.postings[-2]
        cash["meta_data"] = {"fill_uuid": "c7b384f4-3d1c-4a19-b7fe-12c6b2b1040d"}
        report = self.probe()
        self.assertEqual(report["stage"], "wallet_normalization")
        self.assertEqual(report["reason"], "unsupported_wallet_fill_uuid_kind")
        self.assertFalse(report["trade_authorized"])

    def test_delayed_cashflow_and_commission_get_amount_clues_not_credit(self):
        cash = self.broker.postings[-2]
        cash["created_at"] = BASE + 101_000_000
        cash["meta_data"] = {}
        closing_fee = self.broker.postings[3]
        closing_fee["created_at"] = BASE + 102_000_000
        closing_fee["meta_data"] = {}
        report = self.probe()
        self.assertEqual(report["reason"], "unattributed_wallet_posting")
        hints = report["unattributed_wallet_posting_diagnostic"]
        self.assertEqual(hints["count"], 2)
        self.assertEqual([r["posting_kind"] for r in hints["examples"]],
                         ["cashflow", "commission"])
        self.assertTrue(hints["amount_consistency_clues"][0][
            "matches_selected_total_cashflow_exact"])
        self.assertIsNone(hints["amount_consistency_clues"][0][
            "matches_selected_single_fill_commission_exact"])
        self.assertTrue(hints["amount_consistency_clues"][1][
            "matches_selected_single_fill_commission_exact"])
        self.assertFalse(hints["amount_consistency_clues"][1][
            "matches_selected_total_commission_exact"])
        self.assertFalse(hints["amount_matches_prove_broker_attribution"])
        self.assertFalse(hints["other_product_fill_history_checked"])
        self.assertFalse(report["funding_reconciled"])
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertFalse(report["is_net_realized_pnl"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_same_amount_other_trade_fill_is_explicitly_competing_evidence(self):
        fee = self.broker.postings[3]
        fee["created_at"] = BASE + 110_000_000
        fee["meta_data"] = {}
        outside = deepcopy(self.broker.fills[2])
        outside["id"] = "PRIVATE-OTHER-FILL-ID"
        outside["order_id"] = 999
        outside["created_at"] = BASE + 90_000_000
        outside["commission"] = "0.04"
        self.broker.fills.append(outside)
        report = self.probe()
        hints = report["unattributed_wallet_posting_diagnostic"]
        self.assertEqual(report["reason"], "unattributed_wallet_posting")
        self.assertEqual(hints["unowned_same_product_fills_after_last_fill"], 1)
        self.assertTrue(hints["amount_consistency_clues"][0][
            "matches_selected_single_fill_commission_exact"])
        self.assertTrue(hints["amount_consistency_clues"][0][
            "matches_other_same_product_fill_commission_exact"])
        self.assertFalse(hints["amount_matches_prove_broker_attribution"])
        self.assertNotIn("PRIVATE-OTHER-FILL-ID", json.dumps(report))
        self.assertFalse(report["trade_authorized"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_inconsistent_post_close_amount_never_claims_evidence_match(self):
        extra = self.broker.posting("PRIVATE-UNLINKED-ID", "cashflow",
                                    "12345.6789", 110)
        extra["meta_data"] = {"unknown_private_key": "CONFIDENTIAL"}
        self.broker.postings.append(extra)
        report = self.probe()
        self.assertEqual(report["reason"], "unattributed_wallet_posting")
        hints = report["unattributed_wallet_posting_diagnostic"]
        self.assertFalse(hints["amount_consistency_clues"][0][
            "matches_selected_total_cashflow_exact"])
        self.assertNotIn("12345.6789", json.dumps(report))
        self.assertNotIn("PRIVATE-UNLINKED-ID", json.dumps(report))
        self.assertNotIn("CONFIDENTIAL", json.dumps(report))
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_explicit_old_receipt_uses_bounded_historical_window(self):
        later = START + timedelta(days=30)
        with patch.object(self.broker, "product_fills",
                          wraps=self.broker.product_fills) as spy:
            report = self.probe(now=later, fire_id=PRESS)
        self.assertEqual(report["status"],
                         "provisional_read_only_financial_analysis_complete")
        self.assertTrue(report["historical_cutoff_applied"])
        kwargs = spy.call_args.kwargs
        self.assertLess(kwargs["end_time_us"],
                        int(later.timestamp()) * 1_000_000)
        self.assertEqual(kwargs["end_time_us"],
                         BASE + 7*86400*1_000_000 - 1)
        self.assertFalse(report["trade_authorized"])
        self.assertTrue(all(req[0] == "GET" for req in self.broker.calls))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_no_explicit_id_keeps_original_seven_day_selection(self):
        report = self.probe(now=START + timedelta(days=30))
        self.assertEqual(report["stage"], "receipt_selection")
        self.assertEqual(report["reason"], "no_recent_local_bracket_candidate")
        self.assertEqual(self.broker.calls, [])

    def test_invalid_or_nonexistent_requested_id_uses_no_broker_calls(self):
        for requested, expected in (
            ("untrusted", "invalid_requested_fire_id"),
            ("B"*32, "invalid_requested_fire_id"),
            ("b"*32, "requested_receipt_not_eligible"),
        ):
            with self.subTest(fire_id=requested):
                report = self.probe(fire_id=requested)
                self.assertEqual(report["reason"], expected)
                self.assertEqual(self.broker.calls, [])
                self.assertFalse(report["trade_authorized"])

    def test_older_than_historical_limit_does_not_call_broker(self):
        report = self.probe(now=START + timedelta(days=70), fire_id=PRESS)
        self.assertEqual(report["reason"], "requested_receipt_not_eligible")
        self.assertEqual(self.broker.calls, [])
        self.assertFalse(report["historical_cutoff_applied"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_valid_reconciliation_does_not_emit_attribution_hints(self):
        report = self.probe()
        self.assertEqual(report["status"], "provisional_read_only_financial_analysis_complete")
        self.assertIsNone(report["unattributed_wallet_posting_diagnostic"])
        self.assertFalse(report["safe_to_enable_fire"])


if __name__ == "__main__":
    unittest.main()
