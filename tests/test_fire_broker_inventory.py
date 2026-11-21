"""No-network tests of the two-sample, read-only DEMO broker exposure inventory."""
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_broker_inventory import observe_broker_inventory


class FakeClock:
    def __init__(self):
        self.value = 100.0
    def monotonic(self):
        return self.value
    def pause(self, seconds):
        self.value += seconds


class FakeBroker(DeltaDemo):
    def __init__(self, *, allow_orders=False):
        super().__init__(api_key="dummy", api_secret="dummy", allow_orders=allow_orders)
        self.calls = []
        self.margined = []
        self.live = {27: "0", 82: "0"}
        self.open_pages = [([], None)]
        self.cross_margin = False
        self.product_second_id = None
        self.second_sample_hook = None
        self.profile_reads = 0
        self.fail_path = None
        self.malformed_profile = False

    def _request(self, method, path, *, params=None, auth=False, payload=None):
        self.calls.append((method, path, params, auth))
        if method != "GET" or auth is not True or payload is not None:
            raise AssertionError("Broker inventory attempted a mutation or unsigned read")
        if path == self.fail_path:
            raise RuntimeError("PRIVATE PROVIDER SECRET")
        if path == "/v2/profile":
            self.profile_reads += 1
            if self.profile_reads == 2 and self.second_sample_hook:
                self.second_sample_hook()
            return {"result": (None if self.malformed_profile else
                              {"margin_mode": "cross" if self.cross_margin else "isolated"})}
        if path == "/v2/positions/margined":
            return {"result": list(self.margined)}
        if path == "/v2/orders":
            idx = 0 if "after" not in params else 1
            rows, cursor = self.open_pages[idx]
            return {"result": rows, "meta": {"after": cursor}}
        if path in ("/v2/products/BTCUSD", "/v2/products/XAUTUSD"):
            symbol = path.rsplit("/", 1)[1]
            pid = 27 if symbol == "BTCUSD" else 82
            if self.profile_reads == 2 and self.product_second_id and symbol == "XAUTUSD":
                pid = self.product_second_id
            return {"result": {"symbol": symbol, "id": pid,
                               "contract_type": "perpetual_futures"}}
        if path == "/v2/positions":
            pid = params.get("product_id")
            return {"result": {"product_id": pid, "size": self.live.get(pid, "0")}}
        raise AssertionError("Unexpected broker read path: " + path)


class BrokerInventoryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("fire-ops.sqlite", "fire-xaut.sqlite"):
            with sqlite3.connect(self.root / name) as db:
                db.execute("CREATE TABLE fire_requests("
                           "press TEXT PRIMARY KEY, created_at TEXT NOT NULL,"
                           "updated_at TEXT NOT NULL, status TEXT NOT NULL,"
                           "result TEXT NOT NULL)")
        with sqlite3.connect(self.root / "fire-reconciliation.sqlite") as db:
            db.execute("CREATE TABLE reports("
                       "digest TEXT PRIMARY KEY, trade_key TEXT NOT NULL, body TEXT NOT NULL)")
            db.execute("CREATE TABLE evidence(kind TEXT, id TEXT, body TEXT NOT NULL,"
                       "PRIMARY KEY(kind,id))")
            db.execute("CREATE TABLE claims(kind TEXT, id TEXT, trade_key TEXT NOT NULL,"
                       "PRIMARY KEY(kind,id))")
        self.exchange = FakeBroker()
        self.clock = FakeClock()

    def check(self, *, pause=None):
        return observe_broker_inventory(
            self.exchange, self.root,
            pause=self.clock.pause if pause is None else pause,
            monotonic=self.clock.monotonic,
        )

    def test_two_flat_snapshots_are_only_diagnostic_not_trade_permission(self):
        report = self.check()
        self.assertEqual(report["observation_status"],
                         "two_flat_snapshots_observed_not_trade_authority")
        self.assertEqual(report["samples_checked"], 2)
        self.assertTrue(report["sample_interval_verified"])
        self.assertEqual(report["broker_positions_last"], 0)
        self.assertEqual(report["broker_open_orders_last"], 0)
        self.assertEqual(report["realtime_fire_sizes_last"],
                         {"BTCUSD": "0", "XAUTUSD": "0"})
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertFalse(report["is_account_flatness_verified_for_future_orders"])
        self.assertFalse(report["is_complete_broker_trade_history"])
        self.assertFalse(report["is_account_realized_pnl"])
        self.assertEqual(report["ai_calls"], 0)
        self.assertFalse(report["order_mutations"])
        self.assertEqual(len([c for c in self.exchange.calls
                              if c[1] == "/v2/positions/margined"]), 2)
        self.assertFalse(any(c[1] == "/v2/positions" and not c[2]
                             for c in self.exchange.calls))
        self.assertTrue(all(method == "GET" and auth is True
                            for method, _, _, auth in self.exchange.calls))

    def test_second_snapshot_requires_actual_elapsed_interval(self):
        report = self.check(pause=lambda _: None)
        self.assertIn("sample_spacing_not_verified", report["blockers"])
        self.assertEqual(report["samples_checked"], 1)
        self.assertFalse(report["sample_interval_verified"])

    def test_account_wide_exposure_is_detected(self):
        self.exchange.margined = [{"product_id": 999, "size": "-10"}]
        report = self.check()
        self.assertIn("account_has_exposure", report["blockers"])
        self.assertEqual(report["broker_positions_last"], 1)
        self.assertFalse(report["trade_authorized"])

    def test_realtime_gold_exposure_not_hidden_by_lagging_margined_endpoint(self):
        self.exchange.live[82] = "-1"
        report = self.check()
        self.assertIn("fire_market_has_exposure", report["blockers"])
        self.assertIn("lagging_or_inconsistent_broker_positions", report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_non_fire_product_pending_order_is_not_filtered_out(self):
        self.exchange.open_pages = [([{"id": "external", "product_id": 901}], None)]
        report = self.check()
        self.assertEqual(report["broker_open_orders_last"], 1)
        self.assertIn("account_has_open_orders", report["blockers"])
        self.assertTrue(any(c[1] == "/v2/orders" for c in self.exchange.calls))

    def test_real_order_pagination_checks_second_page_and_deduplicates(self):
        first = [{"id": "id-%s" % n, "product_id": 27} for n in range(50)]
        self.exchange.open_pages = [(first, "cursor-1"),
                                    ([first[0], {"id": "different", "product_id": 82}], None)]
        report = self.check()
        self.assertEqual(report["broker_open_orders_last"], 51)
        self.assertIn("account_has_open_orders", report["blockers"])

    def test_broken_pagination_is_not_interpreted_as_zero_orders(self):
        self.exchange.open_pages = [([], "loop"), ([], "loop")]
        report = self.check()
        self.assertIn("open_orders_pagination_unverified", report["blockers"])
        self.assertEqual(report["samples_checked"], 0)
        self.assertFalse(report["trade_authorized"])

    def test_duplicate_broker_order_with_changed_product_fails_closed(self):
        self.exchange.open_pages = [([{"id": "id-a", "product_id": 27}], "cursor"),
                                    ([{"id": "id-a", "product_id": 82}], None)]
        report = self.check()
        self.assertIn("conflicting_broker_order_identity", report["blockers"])

    def test_product_id_change_between_samples_prevents_observation_success(self):
        self.exchange.product_second_id = 83
        report = self.check()
        self.assertIn("fire_product_changed_between_samples", report["blockers"])
        self.assertIn("broker_inventory_changed_between_samples", report["blockers"])

    def test_cross_margin_is_a_blocker_even_with_zero_exposure(self):
        self.exchange.cross_margin = True
        report = self.check()
        self.assertIn("account_isolated_margin_unverified", report["blockers"])

    def test_wrong_client_type_rejected_before_broker_access(self):
        self.exchange.allow_orders = True
        report = self.check()
        self.assertEqual(report["blockers"], ["read_only_delta_demo_client_required"])
        self.assertEqual(self.exchange.calls, [])
        self.exchange.allow_orders = 0
        report = self.check()
        self.assertEqual(report["blockers"], ["read_only_delta_demo_client_required"])
        self.assertEqual(self.exchange.calls, [])

    def test_broker_failure_is_sanitized_and_never_green(self):
        self.exchange.fail_path = "/v2/positions/margined"
        report = self.check()
        self.assertIn("authenticated_broker_read_unavailable", report["blockers"])
        self.assertNotIn("PRIVATE PROVIDER SECRET", json.dumps(report))
        self.assertFalse(report["trade_authorized"])

    def test_invalid_position_quantity_blocks_readiness(self):
        self.exchange.live[27] = float("nan")
        report = self.check()
        self.assertIn("invalid_position_size", report["blockers"])

    def test_local_unresolved_receipt_blocks_even_when_broker_is_flat(self):
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       ("a" * 32, "2026-11-20T10:00:00+00:00",
                        "2026-11-20T10:00:00+00:00",
                        "exposure_unknown", '{"orders_submitted":true}'))
        report = self.check()
        self.assertEqual(report["local_requires_broker_review_count"], 1)
        self.assertIn("local_history_incomplete_or_ambiguous", report["blockers"])

    def test_local_receipt_file_missing_blocks_before_broker_reads(self):
        (self.root / "fire-xaut.sqlite").unlink()
        report = self.check()
        self.assertIn("local_history_incomplete_or_ambiguous", report["blockers"])
        self.assertFalse((self.root / "fire-xaut.sqlite").exists())

    def test_local_receipt_change_during_observation_is_flagged(self):
        def change_file():
            with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
                db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                           ("b" * 32, "2026-11-20T10:00:00+00:00",
                            "2026-11-20T10:00:00+00:00",
                            "exposure_unknown", '{"orders_submitted":null}'))
        self.exchange.second_sample_hook = change_file
        report = self.check()
        self.assertIn("local_evidence_changed_during_broker_observation",
                      report["blockers"])

    def test_unconfirmed_entry_blocks_even_if_parent_receipt_says_flat(self):
        fireid = "a" * 32
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (fireid, "2026-11-20T10:00:00+00:00",
                        "2026-11-20T10:00:00+00:00", "flat_verified",
                        '{"orders_submitted":true,"broker_order_id":"entry-1"}'))
            db.execute("CREATE TABLE fire_entries (press TEXT PRIMARY KEY,"
                       "status TEXT NOT NULL,receipt TEXT NOT NULL)")
            db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                       (fireid, "unconfirmed", "{}"))
        report = self.check()
        self.assertIn("unresolved_local_fire_entries", report["blockers"])
        self.assertEqual(report["local_unresolved_entry_intents"], 1)
        self.assertFalse(report["safe_to_enable_fire"])

    def test_no_order_receipt_with_cancelled_entry_still_fails_closed(self):
        fireid = "a" * 32
        with sqlite3.connect(self.root / "fire-xaut.sqlite") as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (fireid, "2026-11-20T10:00:00+00:00",
                        "2026-11-20T10:00:00+00:00", "rejected_no_order",
                        '{"orders_submitted":false}'))
            db.execute("CREATE TABLE fire_entries (press TEXT PRIMARY KEY,"
                       "status TEXT NOT NULL,receipt TEXT NOT NULL)")
            db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                       (fireid, "cancelled", "{}"))
        report = self.check()
        self.assertIn("local_history_unavailable", report["blockers"])
        self.assertEqual(report["samples_checked"], 0)
        self.assertFalse(report["trade_authorized"])

    def test_same_count_same_status_receipt_change_detected_by_fingerprint(self):
        fireid = "a" * 32
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (fireid, "2026-11-20T10:00:00+00:00",
                        "2026-11-20T10:00:00+00:00", "rejected_no_order",
                        '{"orders_submitted":false,"reason_code":"original"}'))
        def replace_payload():
            with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
                db.execute("UPDATE fire_requests SET result=? WHERE press=?",
                           ('{"orders_submitted":false,"reason_code":"modified"}', fireid))
        self.exchange.second_sample_hook = replace_payload
        report = self.check()
        self.assertEqual(report["local_receipts_total"], 1)
        self.assertEqual(report["samples_checked"], 2)
        self.assertIn("local_evidence_changed_during_broker_observation",
                      report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_new_unresolved_entry_during_broker_reads_is_rejected(self):
        fireid = "b" * 32
        with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (fireid, "2026-11-20T10:00:00+00:00",
                        "2026-11-20T10:00:00+00:00", "flat_verified",
                        '{"orders_submitted":true,"broker_order_id":"entry-1"}'))
            db.execute("CREATE TABLE fire_entries (press TEXT PRIMARY KEY,"
                       "status TEXT NOT NULL,receipt TEXT NOT NULL)")
        def append_entry():
            with sqlite3.connect(self.root / "fire-ops.sqlite") as db:
                db.execute("INSERT INTO fire_entries VALUES (?,?,?)",
                           (fireid, "unconfirmed", "{}"))
        self.exchange.second_sample_hook = append_entry
        report = self.check()
        self.assertIn("local_evidence_changed_during_broker_observation",
                      report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_fill_evidence_same_count_mutation_is_detected(self):
        path = self.root / "fire-reconciliation.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO evidence VALUES (?,?,?)",
                       ("fill", "fill-1", '{"size":"1"}'))
        def mutate():
            with sqlite3.connect(path) as db:
                db.execute("UPDATE evidence SET body=? WHERE id=?",
                           ('{"size":"2"}', "fill-1"))
        self.exchange.second_sample_hook = mutate
        report = self.check()
        self.assertEqual(report["samples_checked"], 2)
        self.assertIn("local_evidence_changed_during_broker_observation",
                      report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_claim_owner_same_count_mutation_is_detected(self):
        path = self.root / "fire-reconciliation.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO claims VALUES (?,?,?)",
                       ("fill", "fill-1", "BTCUSD:" + "a"*32))
        def mutate():
            with sqlite3.connect(path) as db:
                db.execute("UPDATE claims SET trade_key=? WHERE id=?",
                           ("XAUTUSD:" + "b"*32, "fill-1"))
        self.exchange.second_sample_hook = mutate
        report = self.check()
        self.assertEqual(report["samples_checked"], 2)
        self.assertIn("local_evidence_changed_during_broker_observation",
                      report["blockers"])
        self.assertFalse(report["trade_authorized"])

    def test_report_without_evidence_tables_blocks_broker_sweep(self):
        path = self.root / "fire-reconciliation.sqlite"
        key, body = "BTCUSD:" + "a"*32, json.dumps({
            "is_net_realized_pnl": False,
            "reconciliation_as_of_us": 1795000000000000,
        })
        digest = hashlib.sha256((key + chr(10) + body).encode()).hexdigest()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE evidence")
            db.execute("DROP TABLE claims")
            db.execute("INSERT INTO reports VALUES (?,?,?)", (digest, key, body))
        report = self.check()
        self.assertIn("local_history_unavailable", report["blockers"])
        self.assertEqual(report["samples_checked"], 0)
        self.assertEqual(self.exchange.calls, [])
        self.assertFalse(report["trade_authorized"])

    def test_broker_snapshot_change_is_not_disguised_as_two_flat_checks(self):
        self.exchange.second_sample_hook = lambda: setattr(
            self.exchange, "margined", [{"product_id": 999, "size": "7"}])
        report = self.check()
        self.assertIn("broker_inventory_changed_between_samples", report["blockers"])
        self.assertIn("account_has_exposure", report["blockers"])

    def test_live_host_not_admitted(self):
        self.exchange._request = lambda *args, **kwargs: self.fail("Must not read")
        class Live:
            base_url = "https://api.india.delta.exchange"
            allow_orders = False
            _request = self.exchange._request
        report = observe_broker_inventory(Live(), self.root,
            pause=self.clock.pause, monotonic=self.clock.monotonic)
        self.assertEqual(report["blockers"], ["read_only_delta_demo_client_required"])


if __name__ == "__main__":
    unittest.main()
