"""Synthetic offline broker cases; never call an exchange or model."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradebot.chart_desk import ChartDesk
from tradebot.delta import DeltaDemo, DeltaError
from tradebot.fire_execution import FireTradeStore
from tradebot.fire_reconciliation import (ReconciliationError, ReconciliationLedger,
    normalize_fill, reconcile_fire, timestamp_us)

START = datetime(2026, 11, 19, 10, tzinfo=timezone.utc)
BASE = int(START.timestamp()) * 1_000_000
NOW = START + timedelta(minutes=10)
PRESS = "a" * 32


class Broker(DeltaDemo):
    def __init__(self, symbol="BTCUSD"):
        super().__init__()
        self.calls = []
        self.product = {"id": 27, "symbol": symbol, "contract_type": "perpetual_futures",
                        "notional_type": "vanilla", "contract_value": "0.001",
                        "settling_asset": {"symbol": "USD", "precision": 8}}
        self.trade = {"id": PRESS, "created_at": START.isoformat(), "at": START.timestamp(),
                      "status": "flat_verified", "direction": "LONG", "contracts": 2,
                      "broker_order_id": "100", "exit_order_ids": {"take_profit_order": "101", "stop_loss_order": "102"}}
        self.orders = {str(oid): {"id": oid, "client_order_id": PRESS if oid == 100 else "child",
            "product_id": 27, "product_symbol": symbol, "state": "closed" if oid != 102 else "cancelled",
            "size": 2, "unfilled_size": 0 if oid != 102 else 2, "side": "buy" if oid == 100 else "sell",
            "average_fill_price": "60005" if oid == 100 else "60105", "paid_commission": "0.03" if oid == 100 else "0.07",
            "updated_at": BASE + 80_000_000} for oid in (100, 101, 102)}
        self.fills = [dict(id=f"fill-{i}", order_id=oid, product_id=27, product_symbol=symbol,
            product=deepcopy(self.product), fill_type="normal", side="buy" if oid == 100 else "sell",
            size="1", price=str(price), commission=str(fee), settling_asset_symbol="USD",
            created_at=BASE + at * 1_000_000,
            meta_data={"new_position": {"size": position, "realized_funding": "-0.025" if i == 3 else "0"},
                       "ip": "PRIVATE-IP-DO-NOT-SAVE"})
            for i, (oid, price, fee, at, position) in enumerate([
                (100, 60000, "0.01", 10, 1), (100, 60010, "0.02", 20, 2),
                (101, 60100, "0.03", 60, 1), (101, 60110, "0.04", 80, 0)])]
        self.postings = [dict(id=f"fee-{i}", product_id=27, asset_symbol="USD",
            amount=str(-float(f["commission"])), transaction_type="commission", created_at=f["created_at"],
            meta_data={"fill_id": f["id"], "order_id": f["order_id"]}, balance="PRIVATE-BALANCE")
            for i, f in enumerate(self.fills)]
        self.postings += [self.posting("cash", "cashflow", "0.20", 80, order_id=101),
                          self.posting("funding", "funding", "-0.025", 35)]

    def posting(self, eid, kind, amount, at, **refs):
        return dict(id=eid, product_id=27, asset_symbol="USD", amount=amount,
                    transaction_type=kind, created_at=BASE + at * 1_000_000, meta_data=refs)

    def _request(self, method, path, *, params=None, auth=False, **kwargs):
        self.calls.append((method, path, deepcopy(params), auth))
        assert method == "GET", "Reconciliation must never mutate the broker"
        if path.startswith("/v2/products/"):
            return {"result": deepcopy(self.product)}
        if path.startswith("/v2/orders/"):
            assert auth
            return {"result": deepcopy(self.orders[path.rsplit("/", 1)[1]])}
        if path in ("/v2/fills", "/v2/wallet/transactions"):
            assert auth and params["start_time"] == BASE and params["end_time"] == int(NOW.timestamp()) * 1_000_000
            if path == "/v2/fills":
                assert params["product_ids"] == "27"
            return {"result": deepcopy(self.fills if path == "/v2/fills" else self.postings), "meta": {"after": None}}
        raise AssertionError(path)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "reconcile.sqlite"
        self.broker = Broker()

    def run_report(self, broker=None):
        broker = broker or self.broker
        return reconcile_fire(broker, broker.product["symbol"], broker.trade, self.path, now=NOW)

    def assert_unknown(self, reason=None):
        report = self.run_report()
        self.assertFalse(report["is_net_realized_pnl"], report)
        self.assertIsNone(report["net_realized_pnl_usd"])
        self.assertFalse(report["funding_reconciled"])
        if reason:
            self.assertEqual(report["reconciliation_reason"], reason)
        return report

    def _add_signed_foreign_fill(self, *, oid=900, fill_id="foreign-fill", at=5):
        foreign=deepcopy(self.broker.fills[0])
        foreign.update(id=fill_id, order_id=oid,
                       created_at=BASE+at*1_000_000)
        self.broker.fills.append(foreign)

    def test_foreign_signed_fee_posted_during_trade_does_not_corrupt_pnl(self):
        self._add_signed_foreign_fill()
        self.broker.postings.append(self.broker.posting(
            "foreign-fee", "commission", "-0.3", 45,
            order_id=900, fill_id="foreign-fill"))
        report=self.run_report()
        self.assertEqual(report["net_realized_pnl_usd"], "0.075")
        self.assertTrue(report["is_net_realized_pnl"])
        self.assertNotIn("foreign-fee", report["matched_posting_ids"])

    def test_foreign_fill_identity_alias_alone_can_prove_foreign_fee(self):
        self._add_signed_foreign_fill()
        self.broker.postings.append(self.broker.posting(
            "foreign-fee", "commission", "-0.3", 45,
            fill_id="foreign-fill"))
        self.assertEqual(self.run_report()["net_realized_pnl_usd"], "0.075")

    def test_unknown_foreign_order_during_lifecycle_stays_unverified(self):
        self.broker.postings.append(self.broker.posting(
            "ambiguous", "commission", "-0.3", 45, order_id=900))
        self.assert_unknown("overlapping_external_postings")

    def test_cross_referenced_foreign_order_fill_mismatch_stays_blocked(self):
        self._add_signed_foreign_fill()
        self._add_signed_foreign_fill(oid=901,fill_id="foreign2",at=6)
        self.broker.postings.append(self.broker.posting(
            "ambiguous","commission","-0.3",45,
            order_id=900,fill_id="foreign2"))
        self.assert_unknown("overlapping_external_postings")

    def test_foreign_signed_funding_during_lifecycle_is_not_ignored(self):
        self._add_signed_foreign_fill()
        self.broker.postings.append(self.broker.posting(
            "foreign-funding", "funding", "-0.3", 45,
            order_id=900, fill_id="foreign-fill"))
        self.assert_unknown("overlapping_external_postings")

    def test_signed_foreign_fill_inside_position_window_stays_blocked(self):
        self._add_signed_foreign_fill(at=45)
        self.broker.postings.append(self.broker.posting(
            "foreign-fee","commission","-0.3",45,
            order_id=900,fill_id="foreign-fill"))
        self.assert_unknown("overlapping_external_fills")

    def test_uppercase_signed_uuid_matches_lowercase_wallet_alias(self):
        identity = "123e4567-e89b-12d3-a456-426614174000"
        self.broker.fills[0]["id"] = identity.upper()
        meta = self.broker.postings[0]["meta_data"]
        meta.pop("fill_id")
        meta["fill_uuid"] = identity
        report = self.run_report()
        self.assertTrue(report["is_net_realized_pnl"], report)
        self.assertEqual(report["net_realized_pnl_usd"], "0.075")
        self.assertIn(identity, report["matched_fill_ids"])

    def test_uuid_without_hyphens_matches_wallet_fill_uuid(self):
        identity = "123e4567-e89b-12d3-a456-426614174001"
        self.broker.fills[0]["id"] = identity.replace("-", "").upper()
        meta = self.broker.postings[0]["meta_data"]
        meta.pop("fill_id")
        meta["fill_uuid"] = identity
        report = self.run_report()
        self.assertEqual(report["net_realized_pnl_usd"], "0.075")
        self.assertIn(identity, report["matched_fill_ids"])

    def test_raw_fill_id_case_normalizes_like_explicit_wallet_fill_id(self):
        identity = "123e4567-e89b-12d3-a456-426614174002"
        self.broker.fills[0]["id"] = identity.upper()
        self.broker.postings[0]["meta_data"]["fill_id"] = identity
        report = self.run_report()
        self.assertTrue(report["is_net_realized_pnl"])
        self.assertEqual(report["net_realized_pnl_usd"], "0.075")

    def test_unknown_wallet_fill_uuid_still_blocks_pnl(self):
        self.broker.postings[0]["meta_data"].pop("fill_id")
        self.broker.postings[0]["meta_data"]["fill_uuid"] = (
            "123e4567-e89b-12d3-a456-426614174003")
        self.assert_unknown("posting_identity_mismatch")

    def test_long_round_trip_includes_partial_fills_fees_and_funding(self):
        report = self.run_report()
        self.assertEqual(report["net_realized_pnl_usd"], "0.075", report)
        self.assertEqual(report["gross_realized_pnl_usd"], "0.2")
        self.assertEqual(report["reconciled_fees_usd"], "0.1")
        self.assertEqual(report["funding_cashflow_usd"], "-0.025")
        self.assertEqual((report["entry_fill_count"], report["exit_fill_count"]), (2, 2))
        self.assertTrue(report["funding_reconciled"])
        self.assertEqual(len(report["matched_posting_ids"]), 6)
        self.assertTrue(all(call[0] == "GET" for call in self.broker.calls))

    def test_gold_short_round_trip(self):
        self.broker = Broker("XAUTUSD")
        self.broker.trade["direction"] = "SHORT"
        for order in self.broker.orders.values():
            order["side"] = "sell" if order["side"] == "buy" else "buy"
        for fill in self.broker.fills:
            fill["side"] = "sell" if fill["side"] == "buy" else "buy"
            fill["meta_data"]["new_position"]["size"] *= -1
        self.broker.postings[-2]["amount"] = "-0.2"
        self.assertEqual(self.run_report()["net_realized_pnl_usd"], "-0.325")

    def test_partial_entry_cancelled_and_multiple_exit_orders(self):
        self.broker.trade["contracts"] = 3
        self.broker.orders["100"].update(size=3, unfilled_size=1, state="cancelled")
        self.broker.orders["101"].update(size=1)
        self.broker.orders["102"].update(size=1, unfilled_size=0, state="closed")
        self.broker.fills[3]["order_id"] = 102
        self.broker.postings[3]["meta_data"]["order_id"] = 102
        report = self.run_report()
        self.assertEqual(report["filled_contracts"], "2", report)
        self.assertEqual(report["net_realized_pnl_usd"], "0.075")
        self.assertEqual(report["reconciled_entry_price"], "60005")
        self.assertEqual(report["reconciled_exit_price"], "60105")

    def test_maker_rebate_is_not_charged_as_positive_fee(self):
        self.broker.fills[0]["commission"] = "-0.01"
        self.broker.postings[0]["amount"] = "0.01"
        self.assertEqual(self.run_report()["net_realized_pnl_usd"], "0.095")

    def test_weighted_display_averages_do_not_round_realized_pnl(self):
        self.broker.trade["contracts"] = 3
        self.broker.orders["100"]["size"] = 3
        self.broker.orders["101"]["size"] = 3
        for fill, size, position in zip(self.broker.fills, (2, 1, 1, 2), (2, 3, 2, 0)):
            fill["size"] = str(size)
            fill["meta_data"]["new_position"]["size"] = position
        self.broker.postings[-2]["amount"] = "0.31"
        report = self.run_report()
        self.assertEqual(report["net_realized_pnl_usd"], "0.185", report)
        self.assertEqual(report["reconciled_entry_price"], "60003.33333333")
        self.assertEqual(report["reconciled_exit_price"], "60106.66666667")

    def test_deposit_is_excluded_even_in_trade_interval(self):
        self.broker.postings.append(self.broker.posting("deposit", "deposit", "10000", 30))
        report = self.run_report()
        self.assertEqual(report["net_realized_pnl_usd"], "0.075")
        self.assertNotIn("deposit", report["matched_posting_ids"])

    def test_duplicate_pages_and_repeated_reads_do_not_double_count(self):
        self.broker.fills.append(deepcopy(self.broker.fills[0]))
        self.broker.postings.append(deepcopy(self.broker.postings[0]))
        first = self.run_report()
        self.assertEqual(first, self.run_report())
        self.assertEqual(first["net_realized_pnl_usd"], "0.075")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 10)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 1)

    def test_missing_fill_is_not_a_complete_trade(self):
        self.broker.fills.pop(1)
        self.assert_unknown("incomplete_order_fills")

    def test_extra_unowned_fill_inside_position_blocks_attribution(self):
        extra = deepcopy(self.broker.fills[0])
        extra.update(id="manual-fill", order_id=999, created_at=BASE + 30_000_000)
        self.broker.fills.append(extra)
        self.assert_unknown("overlapping_external_fills")

    def test_preexisting_position_is_not_this_trade_profit(self):
        self.broker.fills[0]["meta_data"]["new_position"]["size"] = 3
        self.assert_unknown("position_lifecycle_unverified")

    def test_position_must_be_proven_flat_after_last_fill(self):
        self.broker.fills[-1]["meta_data"]["new_position"]["size"] = 1
        self.assert_unknown("position_lifecycle_unverified")

    def test_settlement_and_liquidation_need_separate_handling(self):
        self.broker.fills[-1]["fill_type"] = "liquidation"
        self.assert_unknown("unsupported_fill_or_currency")

    def test_missing_funding_total_never_means_zero(self):
        del self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"]
        self.assert_unknown("missing_broker_funding_total")

    def test_absent_funding_total_does_not_hide_cashflow_mismatch(self):
        del self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"]
        self.broker.postings[-2]["amount"] = "99"
        report = self.assert_unknown("wallet_cashflow_mismatch")
        self.assertFalse(report["is_net_realized_pnl"])
        self.assertFalse(report["funding_reconciled"])

    def test_absent_funding_total_does_not_hide_commission_mismatch(self):
        del self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"]
        self.broker.postings[0]["amount"] = "99"
        report = self.assert_unknown("wallet_commission_mismatch")
        self.assertFalse(report["is_net_realized_pnl"])
        self.assertFalse(report["funding_reconciled"])

    def test_absent_funding_total_still_rejects_unknown_wallet_adjustments(self):
        del self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"]
        self.broker.postings.append(
            self.broker.posting("tax", "tax", "-0.1", 80, order_id=101))
        report = self.assert_unknown("unsupported_trade_adjustment")
        self.assertFalse(report["is_net_realized_pnl"])

    def test_zero_funding_requires_broker_total_and_complete_wallet(self):
        self.broker.fills[-1]["meta_data"]["new_position"]["realized_funding"] = "0"
        self.broker.postings.pop()
        self.assertEqual(self.run_report()["net_realized_pnl_usd"], "0.1")

    def test_missing_or_mismatched_economic_postings_fail_closed(self):
        original = deepcopy(self.broker.postings)
        for index, reason in ((-1, "wallet_funding_mismatch"), (-2, "wallet_cashflow_mismatch"),
                              (0, "wallet_commission_mismatch")):
            with self.subTest(reason=reason):
                self.broker.postings = deepcopy(original)
                self.broker.postings[index]["amount"] = "99"
                # Independent databases avoid immutable-evidence conflict hiding the mismatch.
                self.path = self.path.with_name(reason + ".sqlite")
                self.assert_unknown(reason)

    def test_no_wallet_history_does_not_invent_postings(self):
        self.broker.postings = []
        self.assert_unknown("missing_cashflow_posting")

    def test_delayed_referenced_funding_is_counted_once(self):
        self.broker.postings[-1].update(created_at=BASE + 100_000_000, meta_data={"order_id": 101})
        self.assertEqual(self.run_report()["net_realized_pnl_usd"], "0.075")

    def test_delayed_unreferenced_posting_stays_unknown(self):
        self.broker.postings[-1]["created_at"] = BASE + 100_000_000
        self.assert_unknown("unattributed_wallet_posting")

    def test_unknown_tax_or_adjustment_cannot_be_silently_ignored(self):
        self.broker.postings.append(self.broker.posting("tax", "tax", "-0.1", 80, order_id=101))
        self.assert_unknown("unsupported_trade_adjustment")

    def test_unscoped_delayed_debit_blocks_net_verification(self):
        extra = self.broker.posting("unknown", "commission", "-0.1", 90)
        extra["product_id"] = None
        self.broker.postings.append(extra)
        self.assert_unknown("unattributed_wallet_posting")

    def test_zero_product_id_is_unscoped_not_an_unrelated_market(self):
        extra = self.broker.posting("unknown", "commission", "-0.1", 90)
        extra["product_id"] = 0
        self.broker.postings.append(extra)
        self.assert_unknown("unattributed_wallet_posting")

    def test_unreferenced_product_postings_need_an_isolated_lifecycle(self):
        for posting in self.broker.postings:
            posting["meta_data"] = {}
        self.assertEqual(self.run_report()["net_realized_pnl_usd"], "0.075")

    def test_missing_page_after_a_success_is_not_cached_as_complete(self):
        self.assertTrue(self.run_report()["is_net_realized_pnl"])
        original = self.broker._request
        def missing_page(method, path, **kwargs):
            if path == "/v2/wallet/transactions":
                return {"result": deepcopy(self.broker.postings), "meta": {"after": "next"}}
            return original(method, path, **kwargs)
        with patch.object(self.broker, "_request", side_effect=missing_page):
            self.assert_unknown("broker_evidence_or_ledger_unavailable")

    def test_currency_mismatch_is_not_converted_or_added(self):
        self.broker.postings[0]["asset_symbol"] = "INR"
        self.assert_unknown("posting_currency_mismatch")

    def test_conflicting_wallet_refs_are_rejected(self):
        self.broker.postings[0]["meta_data"]["order_id"] = 101
        self.assert_unknown("posting_identity_mismatch")

    def test_wrong_client_or_product_identity_blocks_attribution(self):
        self.broker.orders["100"]["client_order_id"] = "different-fire"
        self.assert_unknown("entry_client_id_mismatch")

    def test_active_trade_never_queries_history(self):
        self.broker.trade["status"] = "protected_active"
        self.assert_unknown("trade_not_confirmed_closed")
        self.assertEqual(self.broker.calls, [])

    def test_pending_sibling_order_prevents_final_outcome(self):
        self.broker.orders["102"]["state"] = "pending"
        self.assert_unknown("orders_not_terminal")

    def test_read_only_client_required(self):
        self.broker.allow_orders = True
        self.assert_unknown("read_only_demo_required")
        self.assertEqual(self.broker.calls, [])

    def test_requery_failure_never_returns_previous_verified_result(self):
        self.assertTrue(self.run_report()["is_net_realized_pnl"])
        with patch.object(self.broker, "wallet_postings", side_effect=TimeoutError("SECRET-BROKER-BODY")):
            report = self.assert_unknown("broker_evidence_or_ledger_unavailable")
        self.assertNotIn("SECRET", json.dumps(report))

    def test_changed_evidence_invalidates_result_and_rolls_back_batch(self):
        self.assertTrue(self.run_report()["is_net_realized_pnl"])
        self.broker.postings[0]["amount"] = "-10"
        self.assert_unknown("conflicting_broker_evidence")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT body FROM evidence WHERE kind='posting' AND id='fee-0'").fetchone()
            self.assertEqual(json.loads(row[0])["amount"], "-0.01")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 1)

    def test_private_data_is_not_saved_or_returned(self):
        report = self.run_report()
        self.assertTrue(report["is_net_realized_pnl"])
        self.assertNotIn(b"PRIVATE-", self.path.read_bytes())
        self.assertNotIn("PRIVATE-", json.dumps(report))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_evidence_cannot_be_edited_deleted_or_claimed_twice(self):
        report = self.run_report()
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM evidence")
        ledger = ReconciliationLedger(self.path)
        with self.assertRaisesRegex(ReconciliationError, "evidence_already_attributed"):
            ledger.record("BTCUSD:another-fire", [], [], report)

    def test_same_economic_values_normalize_without_float_rounding(self):
        raw = deepcopy(self.broker.fills[0])
        raw["price"] = "60000.0000"
        raw["commission"] = "0.01000"
        raw["meta_data"]["ip"] = "another-ignored-IP"
        self.assertEqual(normalize_fill(raw), normalize_fill(self.broker.fills[0]))
        for value in (float("nan"), "NaN", "Infinity", True, "-1"):
            with self.subTest(value=value), self.assertRaises(ReconciliationError):
                normalize_fill(dict(raw, size=value))

    def test_broker_timestamp_formats_require_explicit_units(self):
        self.assertEqual(timestamp_us(START.isoformat()), BASE)
        self.assertEqual(timestamp_us(str(BASE)), BASE)
        for value in (START.replace(tzinfo=None).isoformat(), int(START.timestamp()), True):
            with self.subTest(value=value), self.assertRaises(ReconciliationError):
                timestamp_us(value)

    def test_real_scorecard_exposes_reconciled_result_and_caches_reads(self):
        store = FireTradeStore(self.path.parent / "fire-ops.sqlite")
        desk = ChartDesk(self.broker, {"BTCUSD": store})
        with patch("tradebot.fire_reconciliation.datetime") as clock:
            clock.now.return_value = NOW
            clock.fromisoformat = datetime.fromisoformat
            clock.side_effect = datetime
            first = desk.replay("BTCUSD", self.broker.trade)
            second = desk.replay("BTCUSD", self.broker.trade)
        self.assertEqual(first["scorecard"]["net_realized_pnl_usd"], "0.075", first)
        self.assertEqual(first["scorecard"], second["scorecard"])
        self.assertEqual(sum(call[1] == "/v2/fills" for call in self.broker.calls), 1)


class FinancialPaginationTests(unittest.TestCase):
    def client(self, pages):
        client = DeltaDemo()
        mocked = patch.object(client, "_request", side_effect=pages).start()
        self.addCleanup(patch.stopall)
        return client, mocked

    def test_all_pages_requested_with_same_window_and_product(self):
        client, fetch = self.client([
            {"result": [{"id": "1", "product_id": 27}], "meta": {"after": "next"}},
            {"result": [{"id": "1", "product_id": 27}, {"id": "2", "product_id": 27}], "meta": {"after": None}}])
        rows = client.product_fills(27, start_time_us=BASE, end_time_us=BASE + 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(fetch.call_args.kwargs["params"]["after"], "next")
        self.assertTrue(fetch.call_args.kwargs["auth"])

    def test_missing_meta_invalid_cursor_conflict_or_wrong_product_fails(self):
        cases = [
            [{"result": []}],
            [{"result": [], "meta": {}}],
            [{"result": [], "meta": {"after": False}}],
            [{"result": [], "meta": {"after": "a"}}, {"result": [], "meta": {"after": "a"}}],
            [{"result": [{"id": "1", "product_id": 9}], "meta": {"after": None}}],
            [{"result": [{"id": "1", "product_id": 27}, {"id": "1", "product_id": 9}], "meta": {"after": None}}],
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                client, _ = self.client(pages)
                with self.assertRaises(DeltaError):
                    client.product_fills(27, start_time_us=BASE, end_time_us=BASE + 1)

    def test_page_cap_cannot_be_mistaken_for_complete_history(self):
        client, _ = self.client([{"result": [], "meta": {"after": str(i)}} for i in range(40)])
        with self.assertRaises(DeltaError):
            client.wallet_postings(BASE, BASE + 1)


if __name__ == "__main__":
    unittest.main()
