"""Offline tests for read-only Delta DEMO historical bracket/order diagnostics."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_bracket_evidence import audit_bracket_fields

FIRE = "c" * 32


class FakeBroker(DeltaDemo):
    def __init__(self, *, allow_orders=False):
        super().__init__(api_key="unused", api_secret="unused",
                         allow_orders=allow_orders)
        self.calls = []
        self.private_response_failure = False
        self.product = {"id": 27, "symbol": "BTCUSD",
                        "contract_type": "perpetual_futures"}
        self.orders = {
            "101": {"id": 101, "product_id": 27, "client_order_id": FIRE,
                    "side": "buy", "size": 2, "state": "closed", "unfilled_size": 0},
            "102": {"id": "102", "product_id": 27, "side": "sell",
                    "size": "2", "state": "cancelled",
                    "stop_order_type": "stop_loss_order", "stop_price": "95",
                    "bracket_order": True},
            "103": {"id": 103, "product_id": 27, "side": "sell",
                    "size": "2", "state": "closed",
                    "stop_order_type": "take_profit_order", "stop_price": "110",
                    "bracket_order": True},
        }

    def _request(self, method, path, *, auth=False, params=None, payload=None):
        self.calls.append((method, path, auth, params, payload))
        if method != "GET" or auth is not True or params is not None \
                or payload is not None:
            raise AssertionError("A non-read-only broker request was attempted")
        if self.private_response_failure:
            raise RuntimeError("DO NOT LEAK PRIVATE API KEY")
        if path == "/v2/products/BTCUSD":
            return {"result": dict(self.product)}
        if path.startswith("/v2/orders/"):
            order_id = path.removeprefix("/v2/orders/")
            return {"result": dict(self.orders[order_id])}
        raise AssertionError("Unexpected broker request")


class BracketEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dbpath = self.root / "fire-ops.sqlite"
        with sqlite3.connect(self.dbpath) as db:
            db.execute("CREATE TABLE fire_requests("
                       "press TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,"
                       "status TEXT, result TEXT)")
            db.execute("CREATE TABLE fire_entries("
                       "press TEXT PRIMARY KEY, status TEXT, receipt TEXT)")
        self.exchange = FakeBroker()
        self.saved = {
            "orders_submitted": True, "direction": "LONG",
            "contracts": 2, "stop_loss": "95", "take_profit": "110",
            "broker_order_id": "101",
            "exit_order_ids": {
                "stop_loss_order": "102", "take_profit_order": "103",
            },
        }
        self.write_saved()

    def write_saved(self, *, entry_id="101", body=None):
        with sqlite3.connect(self.dbpath) as db:
            db.execute("DELETE FROM fire_requests")
            db.execute("DELETE FROM fire_entries")
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (FIRE, "2026-11-20T05:00:00+00:00",
                        "2026-11-20T06:00:00+00:00", "flat_verified",
                        json.dumps(self.saved if body is None else body)))
            if entry_id is not None:
                entry = {
                    "press": FIRE, "symbol": "BTCUSD", "product_id": 27,
                    "order_id": entry_id, "status": "filled",
                    "plan": {
                        "direction": "LONG", "contracts": 2,
                        "stop_loss": "95", "take_profit": "110",
                    },
                }
                db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                           (FIRE, "filled", json.dumps(entry)))

    def run_check(self, *, symbol="BTCUSD", fire_id=FIRE):
        return audit_bracket_fields(self.exchange, self.root,
                                    symbol=symbol, fire_id=fire_id)

    def test_three_authenticated_gets_are_only_observation_not_authority(self):
        result = self.run_check()
        self.assertEqual(result["observation_status"],
                         "historical_order_fields_match_not_protection_proof")
        self.assertEqual(result["authenticated_order_gets"], 3)
        self.assertTrue(result["local_evidence_stable_across_order_reads"])
        self.assertEqual(result["historical_child_states"],
                         {"stop_loss_order": "cancelled",
                          "take_profit_order": "closed"})
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["is_historical_protection_proven"])
        self.assertFalse(result["is_current_account_flatness_proven"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["order_mutations"])
        self.assertEqual(result["ai_calls"], 0)
        self.assertEqual(len(self.exchange.calls), 4)
        self.assertTrue(all(method == "GET" and auth is True and
                            params is None and payload is None
                            for method, _, auth, params, payload
                            in self.exchange.calls))
        self.assertNotIn("101", json.dumps(result))

    def test_receipt_changed_during_last_broker_get_is_blocked(self):
        original_request = self.exchange._request
        def mutate_after_read(method, path, **kwargs):
            response = original_request(method, path, **kwargs)
            if path == "/v2/orders/103":
                changed = dict(self.saved, take_profit="111")
                with sqlite3.connect(self.dbpath) as db:
                    db.execute("UPDATE fire_requests SET result=? WHERE press=?",
                               (json.dumps(changed), FIRE))
                    db.commit()
            return response
        self.exchange._request = mutate_after_read
        result = self.run_check()
        self.assertEqual(result["authenticated_order_gets"], 3)
        self.assertIn("local_fire_evidence_changed_during_broker_reads",
                      result["blockers"])
        self.assertEqual(result["observation_status"], "review_required")
        self.assertFalse(result["local_evidence_stable_across_order_reads"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["safe_to_enable_fire"])

    def test_unrelated_local_receipt_changes_also_block_historical_audit(self):
        another = "d" * 32
        with sqlite3.connect(self.dbpath) as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (another, "2026-11-19T05:00:00+00:00",
                        "2026-11-19T06:00:00+00:00", "flat_verified",
                        '{"orders_submitted":true}'))
        original_request = self.exchange._request
        def mutate_unrelated_receipt(method, path, **kwargs):
            response = original_request(method, path, **kwargs)
            if path == "/v2/orders/102":
                with sqlite3.connect(self.dbpath) as db:
                    db.execute("UPDATE fire_requests SET result=? WHERE press=?",
                               ('{"orders_submitted":false}', another))
            return response
        self.exchange._request = mutate_unrelated_receipt
        result = self.run_check()
        self.assertIn("local_fire_evidence_changed_during_broker_reads",
                      result["blockers"])
        self.assertFalse(result["local_evidence_stable_across_order_reads"])
        self.assertEqual(result["authenticated_order_gets"], 3)

    def test_source_deleted_during_broker_reads_fails_without_recreating_db(self):
        original_request = self.exchange._request
        def unlink_after_read(method, path, **kwargs):
            response = original_request(method, path, **kwargs)
            if path == "/v2/orders/103":
                self.dbpath.unlink()
            return response
        self.exchange._request = unlink_after_read
        result = self.run_check()
        self.assertIn("local_fire_evidence_changed_or_unavailable",
                      result["blockers"])
        self.assertFalse(self.dbpath.exists())
        self.assertFalse(result["local_evidence_stable_across_order_reads"])
        self.assertFalse(result["is_historical_protection_proven"])
        self.assertFalse(result["trade_authorized"])

    def test_child_order_size_missing_or_wrong_is_not_accepted(self):
        for wrong in ("1", "3", None, False, "NaN"):
            with self.subTest(wrong=wrong):
                self.exchange.orders["102"]["size"] = wrong
                result = self.run_check()
                self.assertEqual(result["observation_status"], "review_required")
                self.assertTrue(any("contract_size" in x
                                    for x in result["blockers"]))
                self.assertFalse(result["trade_authorized"])

    def test_wrong_child_type_price_and_parent_identity_fail_closed(self):
        tests = (
            ("102", "stop_order_type", "take_profit_order",
             "stop_loss_order_broker_identity_unverified"),
            ("102", "stop_price", "94", "stop_loss_order_broker_trigger_mismatch"),
            ("103", "bracket_order", False,
             "take_profit_order_broker_identity_unverified"),
            ("101", "client_order_id", "different",
             "broker_parent_fill_identity_or_state_unverified"),
            ("101", "size", "1", "broker_parent_contract_size_mismatch"),
        )
        for order_id, field, value, expected in tests:
            with self.subTest(order_id=order_id, field=field):
                saved = self.exchange.orders[order_id][field]
                self.exchange.orders[order_id][field] = value
                self.assertIn(expected, self.run_check()["blockers"])
                self.exchange.orders[order_id][field] = saved

    def test_unknown_broker_child_state_fails_closed(self):
        self.exchange.orders["103"]["state"] = "unknown_provider_state"
        report = self.run_check()
        self.assertIn("take_profit_order_broker_state_unverified", report["blockers"])

    def test_broker_order_id_mismatch_fails_closed(self):
        self.exchange.orders["103"]["id"] = "999"
        report = self.run_check()
        self.assertIn("broker_order_identity_mismatch", report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_duplicate_local_ids_stop_before_broker_get(self):
        self.saved["exit_order_ids"]["take_profit_order"] = "102"
        self.write_saved()
        result = self.run_check()
        self.assertIn("duplicate_saved_order_identity", result["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_missing_entry_broker_id_conflict_stops_before_get(self):
        self.write_saved(entry_id="111")
        result = self.run_check()
        self.assertIn("local_parent_order_identity_conflict", result["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_original_entry_plan_conflicts_block_before_any_broker_request(self):
        # The initial entry plan is independently persisted by FireEntries.
        # Matching only the parent order ID would miss each inconsistency.
        changes = (
            ("direction", "SHORT"),
            ("contracts", 3),
            ("stop_loss", "94"),
            ("take_profit", "111"),
        )
        for key, value in changes:
            with self.subTest(plan_field=key):
                self.write_saved()
                with sqlite3.connect(self.dbpath) as db:
                    row = json.loads(db.execute(
                        "SELECT receipt FROM fire_entries WHERE press=?", (FIRE,)
                    ).fetchone()[0])
                    row["plan"][key] = value
                    db.execute("UPDATE fire_entries SET receipt=? WHERE press=?",
                               (json.dumps(row), FIRE))
                self.exchange.calls.clear()
                result = self.run_check()
                self.assertIn("local_entry_trade_plan_conflict", result["blockers"])
                self.assertEqual(result["authenticated_order_gets"], 0)
                self.assertEqual(self.exchange.calls, [])
                self.assertFalse(result["trade_authorized"])

    def test_incomplete_original_entry_plan_blocks_before_broker_read(self):
        self.write_saved()
        with sqlite3.connect(self.dbpath) as db:
            row = json.loads(db.execute(
                "SELECT receipt FROM fire_entries WHERE press=?", (FIRE,)
            ).fetchone()[0])
            del row["plan"]["take_profit"]
            db.execute("UPDATE fire_entries SET receipt=? WHERE press=?",
                       (json.dumps(row), FIRE))
        report = self.run_check()
        self.assertIn("local_entry_trade_plan_unverified", report["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_durable_entry_identity_and_status_contradictions_block(self):
        edits = (
            ("press", "d" * 32, "local_entry_market_identity_conflict"),
            ("symbol", "XAUTUSD", "local_entry_market_identity_conflict"),
            ("product_id", 82, "local_entry_broker_product_identity_conflict"),
            ("product_id", True, "local_entry_market_identity_conflict"),
            ("status", "cancelled", "local_entry_filled_state_unverified"),
        )
        for key, value, expected in edits:
            with self.subTest(entry_field=key, value=value):
                self.write_saved()
                with sqlite3.connect(self.dbpath) as db:
                    row = json.loads(db.execute(
                        "SELECT receipt FROM fire_entries WHERE press=?", (FIRE,)
                    ).fetchone()[0])
                    row[key] = value
                    db.execute("UPDATE fire_entries SET receipt=? WHERE press=?",
                               (json.dumps(row), FIRE))
                self.exchange.calls.clear()
                report = self.run_check()
                self.assertIn(expected, report["blockers"])
                self.assertFalse(report["trade_authorized"])
                if key != "product_id" or value is True:
                    self.assertEqual(self.exchange.calls, [])
                else:
                    self.assertEqual(len(self.exchange.calls), 1)
                    self.assertEqual(report["authenticated_order_gets"], 0)

    def test_durable_entry_row_state_disagrees_with_body_and_blocks(self):
        self.write_saved()
        with sqlite3.connect(self.dbpath) as db:
            db.execute("UPDATE fire_entries SET status='accepted' WHERE press=?", (FIRE,))
        report = self.run_check()
        self.assertIn("local_entry_filled_state_unverified", report["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_historical_local_no_entry_still_yields_limited_broker_diagnostic(self):
        # Some legacy receipts predate durable entry intent; a matching
        # broker comparison still cannot establish historical protection.
        self.write_saved(entry_id=None)
        report = self.run_check()
        self.assertEqual(report["observation_status"],
                         "historical_order_fields_match_not_protection_proof")
        self.assertFalse(report["is_historical_protection_proven"])
        self.assertFalse(report["trade_authorized"])

    def test_no_order_or_unknown_fire_receipt_never_contacts_broker(self):
        self.saved["orders_submitted"] = False
        self.write_saved()
        self.assertIn("no_submitted_order_receipt",
                      self.run_check()["blockers"])
        self.assertIn("invalid_fire_identity",
                      self.run_check(fire_id="../bad")["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_missing_source_file_never_created_and_no_broker_get(self):
        self.dbpath.unlink()
        report = self.run_check()
        self.assertIn("local_fire_ledger_unverified", report["blockers"])
        self.assertFalse(self.dbpath.exists())
        self.assertEqual(self.exchange.calls, [])

    def test_order_enabled_client_rejected_even_if_demo(self):
        self.exchange = FakeBroker(allow_orders=True)
        result = self.run_check()
        self.assertIn("read_only_delta_demo_client_required", result["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_private_error_message_never_enters_output(self):
        self.exchange.private_response_failure = True
        result = self.run_check()
        self.assertIn("authenticated_broker_order_read_unavailable",
                      result["blockers"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("KEY", json.dumps(result))

    def test_product_identity_conflict_is_review_required(self):
        self.exchange.product["id"] = 82
        result = self.run_check()
        self.assertIn("broker_parent_fill_identity_or_state_unverified",
                      result["blockers"])
        self.assertFalse(result["trade_authorized"])


if __name__ == "__main__":
    unittest.main()
