"""Signed recovery planning is deliberately unable to clear locks or execute."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from equity_fixtures import receipt_for
from test_fire_release_gate import ProfileReadOnly
from tradebot.commissioning_equity import signed_equity_readiness
from tradebot.commissioning_review import (
    LOCK_NAME, PACKET_SCHEMA, REVIEW_SCHEMA, ReviewError, attempt_evidence,
    capture_packet, digest, load_key, main, review_packet, seal, verify, write_exclusive,
)
from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.equity_monitor import MonitorStore
from tradebot.fire_commission_preflight import commissioning_preflight
from tradebot.fire_execution import FireTradeStore
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, stamp


def ready(*_):
    return {"ready_for_supervised_operator_review":True, "broker_flat_two_samples":True,
            "both_fire_endpoints_disabled":True, "watchdog_and_dashboard_active":True,
            "equity_prerequisites_verified":True, "trade_authorized":False, "blockers":[]}


class ReadOnlyBroker(ProfileReadOnly):
    """Exercise the real pagination/identity helper with entirely offline GETs."""
    _account_history = DeltaDemo._account_history
    product_fills = DeltaDemo.product_fills

    def __init__(self, now):
        super().__init__()
        self.now = now
        self.fill_page = {"result":[], "meta":{"after":None}}
        self.fail_fills = False

    def _request(self, method, path, *, auth=False, params=None):
        if method != "GET":
            raise AssertionError("Broker mutation attempted")
        if path == "/v2/fills":
            if not auth:
                raise AssertionError("Unauthenticated financial evidence")
            self.calls.append((method, path))
            if self.fail_fills:
                raise TimeoutError("private broker credential must not leak")
            return self.fill_page
        result = super()._request(method, path, auth=auth, params=params)
        if path == "/v2/products/XAUTUSD":
            result["result"]["tick_size"] = "0.01"
        return result

    def ticker(self, symbol):
        self.calls.append(("GET", "/v2/tickers/" + symbol))
        return {"symbol":symbol, "product_id":82, "tick_size":"0.01"}

    def wallet_balances(self):
        self.calls.append(("GET", "/v2/wallet/balances"))
        return {"meta":{"net_equity":"1000"}, "equity_read_receipt":receipt_for(at=self.now)}


class CommissioningReviewTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = datetime.now(timezone.utc)
        self.created = self.now - timedelta(minutes=10)
        self.updated = self.now - timedelta(minutes=9)
        self.fire_id = "a" * 32
        self.database = self.root / "fire-xaut.sqlite"
        store = FireTradeStore(self.database)
        store.reserve(when=self.created, press=self.fire_id)
        store.update(self.fire_id, "rejected_no_order", orders_submitted=False,
                     reason_code="portfolio_equity_limits_failed")
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE fire_requests SET updated_at=?", (self.updated.isoformat(),))
        self.lock = self.root / LOCK_NAME
        self.lock.write_bytes(b"")
        lock_ns = stamp(self.created) * 1000
        os.utime(self.lock, ns=(lock_ns, lock_ns))
        self.capture_key = Ed25519PrivateKey.generate()  # fixture keys only
        self.operator_key = Ed25519PrivateKey.generate()
        self.broker = ReadOnlyBroker(self.now)

    def packet(self, **kwargs):
        return capture_packet(self.broker, self.root, self.fire_id, self.capture_key,
                              readiness=kwargs.pop("readiness", ready), now=self.now, **kwargs)

    def review(self, packet, *, decision="accept_for_recovery_planning", now=None):
        return review_packet(packet, self.capture_key.public_key(), self.operator_key,
                             self.root, decision=decision, now=now or self.now)

    def snapshot(self):
        with closing(sqlite3.connect(self.database)) as db:
            evidence = "\n".join(db.iterdump())
        return evidence, self.lock.read_bytes(), self.lock.stat().st_mtime_ns

    def test_signed_capture_and_separate_review_preserve_every_original_record(self):
        before = self.snapshot()
        packet = self.packet()
        payload = verify(packet, self.capture_key.public_key(), PACKET_SCHEMA)
        self.assertTrue(payload["ready_for_recovery_planning"])
        self.assertTrue(payload["historical_fills"]["verified"])
        self.assertEqual(payload["historical_fills"]["fill_count"], 0)
        self.assertEqual(payload["signature_scope"], "local_attestation_of_authenticated_demo_reads")
        review = self.review(packet)
        recorded = verify(review, self.operator_key.public_key(), REVIEW_SCHEMA)
        self.assertEqual(recorded["packet_sha256"], digest(packet))
        for value in (payload, recorded):
            self.assertIs(value["trade_authorized"], False)
            self.assertIs(value["lock_released"], False)
            self.assertIs(value["separate_recovery_and_execution_approval_required"], True)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(all(method == "GET" for method, _ in self.broker.calls))

    def test_real_preflight_equity_gate_and_historical_pagination_integrate(self):
        # No production state: synthesize authentic-time fixture anchors only.
        self.now = datetime(2026, 11, 23, 0, 10, tzinfo=timezone.utc)
        self.broker.now = self.now
        # Keep the historical attempt relative to the test clock, independently
        # of the calendar date on which CI executes this fixture.
        created, updated = self.now - timedelta(minutes=10), self.now - timedelta(minutes=9)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE fire_requests SET created_at=?,updated_at=?",
                       (created.isoformat(), updated.isoformat()))
        os.utime(self.lock, ns=(stamp(created)*1000, stamp(created)*1000))
        FireTradeStore(self.root / "fire-ops.sqlite")
        guard = PortfolioEquityGuard(self.root / "fire-equity-risk.sqlite")
        for at in (self.now.replace(minute=1), self.now - timedelta(seconds=1)):
            guard.observe_verified_read("1000", receipt_for(at=at), now=at)
        monitor = MonitorStore(self.root / "fire-monitoring.sqlite")
        for service in ("watchdog", "equity_collector"):
            monitor.heartbeat(service, at=self.now)
        delays = []
        clock = [100.0]
        def advance(seconds):
            delays.append(seconds)
            clock[0] += seconds
        readiness = partial(commissioning_preflight, pause=advance,
                            monotonic=lambda: clock[0],
                            check_services=lambda:True, check_fire=lambda:True,
                            check_equity=partial(signed_equity_readiness, now=self.now))
        before = self.snapshot()
        packet = self.packet(readiness=readiness)
        self.assertTrue(packet["payload"]["ready_for_recovery_planning"])
        self.assertEqual(delays, [11])
        self.assertEqual(self.broker.calls.count(("GET", "/v2/positions/margined")), 2)
        self.assertEqual(self.broker.calls.count(("GET", "/v2/fills")), 1)
        self.assertEqual(self.broker.calls.count(("GET", "/v2/wallet/balances")), 1)
        self.review(packet)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(method == "GET" for method, _ in self.broker.calls))

    def test_readonly_demo_required_before_any_broker_or_database_read(self):
        for url, allow in (("https://api.india.delta.exchange", False), (DEMO_API, True)):
            self.broker.base_url, self.broker.allow_orders = url, allow
            with self.assertRaisesRegex(ReviewError, "read_only_demo_client_required"):
                self.packet()
        self.assertEqual(self.broker.calls, [])

    def test_payload_tampering_and_wrong_trust_pin_are_rejected(self):
        packet = self.packet()
        tampered = deepcopy(packet)
        tampered["payload"]["prior_attempt"]["reason_code"] = "different"
        with self.assertRaisesRegex(ReviewError, "invalid_signature"):
            self.review(tampered)
        with self.assertRaisesRegex(ReviewError, "untrusted_signer"):
            review_packet(packet, self.operator_key.public_key(), self.capture_key,
                          self.root, decision="reject", now=self.now)

    def test_capture_signer_cannot_be_its_own_operator_reviewer(self):
        with self.assertRaisesRegex(ReviewError, "separate_operator_key_required"):
            review_packet(self.packet(), self.capture_key.public_key(), self.capture_key,
                          self.root, decision="accept_for_recovery_planning", now=self.now)

    def test_stale_future_or_boundary_expired_packet_cannot_be_accepted(self):
        packet = self.packet()
        for when in (self.now + timedelta(seconds=120, microseconds=1), self.now - timedelta(microseconds=1)):
            with self.subTest(when=when), self.assertRaisesRegex(ReviewError, "stale_or_future_capture"):
                self.review(packet, now=when)
        self.review(packet, now=self.now + timedelta(seconds=120))
        rejected = self.review(packet, decision="reject", now=self.now + timedelta(days=1))
        self.assertEqual(rejected["payload"]["decision"], "reject")

    def test_inconsistent_signed_readiness_is_not_accepted_just_because_signed(self):
        packet = self.packet()
        variants = []
        for section, key, value in (("preflight", "equity_prerequisites_verified", False),
                                    ("prior_attempt", "entry_intent_present", True),
                                    ("historical_fills", "verified", False),
                                    ("historical_fills", "fill_count", True),
                                    ("historical_fills", "end_us", 1)):
            changed = deepcopy(packet["payload"])
            changed[section][key] = value
            variants.append(changed)
        for payload in variants:
            with self.subTest(payload=payload), self.assertRaises(ReviewError):
                self.review(seal(payload, self.capture_key))

    def test_execution_permission_or_changed_scope_is_never_a_review_option(self):
        packet = self.packet()
        for key, value in (("trade_authorized", True), ("lock_released", True),
                           ("environment", "live"), ("symbol", "BTCUSD"),
                           ("separate_recovery_and_execution_approval_required", False)):
            changed = deepcopy(packet["payload"])
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ReviewError, "invalid_review_scope"):
                self.review(seal(changed, self.capture_key))
        with self.assertRaises(ReviewError):
            self.review(packet, decision="execute")

    def test_missing_risk_or_watchdog_prerequisite_creates_blocked_signed_record(self):
        gate = ready()
        gate["equity_prerequisites_verified"] = False
        packet = self.packet(readiness=lambda *_:gate)
        self.assertFalse(packet["payload"]["ready_for_recovery_planning"])
        self.assertIn("commissioning_prerequisites_incomplete", packet["payload"]["blockers"])
        with self.assertRaises(ReviewError):
            self.review(packet)
        self.review(packet, decision="reject")

    def test_network_failure_never_becomes_an_empty_fill_window(self):
        self.broker.fail_fills = True
        packet = self.packet()
        self.assertFalse(packet["payload"]["historical_fills"]["verified"])
        self.assertIn("historical_broker_fills_not_verified", packet["payload"]["blockers"])
        self.assertNotIn("private broker credential", json.dumps(packet))
        self.assertEqual(self.broker.calls.count(("GET", "/v2/fills")), 1)
        with self.assertRaises(ReviewError):
            self.review(packet)

    def test_partial_or_unpaginated_history_cannot_prove_no_fills(self):
        for page in ({"result":[]}, {"result":[], "meta":{"after":"loop"}},
                     {"result":[{"id":1,"product_id":27}], "meta":{"after":None}}):
            with self.subTest(page=page):
                self.broker.fill_page = page
                packet = self.packet()
                self.assertFalse(packet["payload"]["ready_for_recovery_planning"])
                self.assertFalse(packet["payload"]["historical_fills"]["verified"])

    def test_any_broker_fill_in_attempt_window_requires_full_reconciliation(self):
        self.broker.fill_page["result"] = [{"id":7,"product_id":82, "size":1}]
        packet = self.packet()
        self.assertEqual(packet["payload"]["historical_fills"]["fill_count"], 1)
        self.assertIn("broker_fills_exist_in_attempt_window", packet["payload"]["blockers"])
        with self.assertRaises(ReviewError):
            self.review(packet)

    def test_unknown_submission_flag_or_broker_reference_blocks_short_recovery(self):
        for fields in ({}, {"orders_submitted":True}, {"orders_submitted":False,"broker_order_id":1},
                       {"orders_submitted":False,"broker_order_id":0},
                       {"orders_submitted":False,"order_state":"filled"},
                       {"orders_submitted":False,"protection_verified":True}):
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("UPDATE fire_requests SET result=?", (json.dumps(fields),))
            packet = self.packet()
            self.assertIn("prior_attempt_requires_full_fill_and_order_reconciliation", packet["payload"]["blockers"])

    def test_durable_entry_intent_blocks_even_with_rejected_parent(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE fire_entries(press TEXT PRIMARY KEY, status TEXT, receipt TEXT)")
            db.execute("INSERT INTO fire_entries VALUES (?,?,?)", (self.fire_id, "unconfirmed", "{}"))
        packet = self.packet()
        self.assertFalse(packet["payload"]["ready_for_recovery_planning"])
        with self.assertRaises(ReviewError):
            self.review(packet)

    def test_receipt_changed_during_capture_is_not_signed(self):
        def race(*_):
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("UPDATE fire_requests SET result='{}'")
            return ready()
        with self.assertRaisesRegex(ReviewError, "changed_during_capture"):
            self.packet(readiness=race)

    def test_lock_changed_after_capture_is_not_approved(self):
        packet = self.packet()
        self.lock.write_bytes(b"changed")
        with self.assertRaisesRegex(ReviewError, "changed_since_capture"):
            self.review(packet)
        self.assertEqual(self.lock.read_bytes(), b"changed")

    def test_receipt_changed_after_capture_requires_new_review(self):
        packet = self.packet()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE fire_requests SET result='{}'")
        with self.assertRaisesRegex(ReviewError, "changed_since_capture"):
            self.review(packet)

    def test_newer_request_prevents_old_attempt_recovery(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       ("b"*32, self.now.isoformat(), self.now.isoformat(), "requested", "{}"))
        with self.assertRaisesRegex(ReviewError, "not_latest_gold_request"):
            self.packet()

    def test_equal_timestamp_requests_cannot_claim_an_unambiguous_latest_attempt(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       ("b"*32, self.created.isoformat(), self.created.isoformat(), "requested", "{}"))
        with self.assertRaisesRegex(ReviewError, "not_latest_gold_request"):
            self.packet()

    def test_other_receipt_changes_invalidate_the_captured_inventory(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            before = (self.created - timedelta(minutes=20)).isoformat()
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       ("b"*32, before, before, "rejected_no_order", '{"orders_submitted":false}'))
        packet = self.packet()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE fire_requests SET status='exposure_unknown' WHERE press=?", ("b"*32,))
        with self.assertRaisesRegex(ReviewError, "changed_since_capture"):
            self.review(packet)

    def test_absent_symlinked_or_uncorrelated_lock_is_not_recovered(self):
        os.utime(self.lock, ns=(1, 1))
        self.assertIn("commissioning_lock_not_correlated_with_attempt", self.packet()["payload"]["blockers"])
        self.lock.unlink()
        with self.assertRaises(OSError):
            self.packet()
        self.lock.symlink_to(self.database)
        with self.assertRaises(OSError):
            self.packet()

    def test_fifo_input_is_rejected_without_blocking(self):
        self.lock.unlink()
        os.mkfifo(self.lock)
        with self.assertRaisesRegex(ReviewError, "invalid_evidence_file"):
            self.packet()

    def test_corrupt_database_is_not_repaired_and_nothing_calls_broker(self):
        self.database.write_bytes(b"corrupt original receipt")
        with self.assertRaises(sqlite3.DatabaseError):
            self.packet()
        self.assertEqual(self.database.read_bytes(), b"corrupt original receipt")
        self.assertEqual(self.broker.calls, [])

    def test_too_recent_attempt_does_not_query_potentially_unsettled_history(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE fire_requests SET updated_at=?", (self.now.isoformat(),))
        packet = self.packet()
        self.assertIn("prior_attempt_settlement_window_not_ready", packet["payload"]["blockers"])
        self.assertNotIn(("GET", "/v2/fills"), self.broker.calls)

    def test_capture_timeout_and_wall_clock_jump_fail_closed(self):
        with patch("tradebot.commissioning_review.time.monotonic_ns", side_effect=[0, 121_000_000_000]):
            with self.assertRaisesRegex(ReviewError, "clock_inconsistent"):
                self.packet()
        with patch("tradebot.commissioning_review.datetime", wraps=datetime) as clock:
            clock.now.side_effect = [self.now, self.now + timedelta(seconds=2)]
            with patch("tradebot.commissioning_review.time.monotonic_ns", return_value=0):
                with self.assertRaisesRegex(ReviewError, "clock_inconsistent"):
                    capture_packet(self.broker, self.root, self.fire_id, self.capture_key, readiness=ready)

    def test_restart_and_concurrent_output_writers_cannot_overwrite_packet(self):
        packet = self.packet()
        path = self.root / "packet.json"
        def write(_):
            try:
                write_exclusive(path, packet)
                return 1
            except FileExistsError:
                return 0
        with ThreadPoolExecutor(max_workers=8) as workers:
            self.assertEqual(sum(workers.map(write, range(16))), 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded, packet)
        self.review(loaded)
        with self.assertRaises(FileExistsError):
            write_exclusive(self.lock, packet)
        self.assertEqual(self.lock.read_bytes(), b"")

    def test_crashed_partial_packet_is_retained_and_cannot_be_overwritten(self):
        path = self.root / "partial.json"
        path.write_text('{"payload":')
        with self.assertRaises(FileExistsError):
            write_exclusive(path, self.packet())
        self.assertEqual(path.read_text(), '{"payload":')

    def save_keys(self):
        paths = {}
        for name, key in (("capture", self.capture_key), ("operator", self.operator_key)):
            private = self.root / (name + ".pem")
            private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
            private.chmod(0o600)
            public = self.root / (name + ".pub")
            public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                             serialization.PublicFormat.SubjectPublicKeyInfo))
            paths[name] = private
            paths[name + "_public"] = public
        return paths

    def test_signing_keys_require_private_permissions_and_trusted_key_type(self):
        keys = self.save_keys()
        load_key(keys["capture"], private=True)
        load_key(keys["capture_public"])
        keys["capture"].chmod(0o644)
        with self.assertRaisesRegex(ReviewError, "private_file_permissions"):
            load_key(keys["capture"], private=True)
        with self.assertRaises(ReviewError):
            load_key(keys["capture_public"], private=True)

    def test_cli_review_persists_a_signed_non_authorizing_record_and_refuses_replay_output(self):
        packet = self.root / "capture.json"
        write_exclusive(packet, self.packet())
        keys = self.save_keys()
        output = self.root / "review.json"
        args = ["review", "--data-dir", str(self.root), "--packet", str(packet),
                "--trusted-capture-key", str(keys["capture_public"]), "--operator-key", str(keys["operator"]),
                "--decision", "accept_for_recovery_planning", "--output", str(output)]
        before = self.snapshot()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)
        self.assertNotIn("PRIVATE KEY", stdout.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue())
        record = verify(json.loads(output.read_text()), self.operator_key.public_key(), REVIEW_SCHEMA)
        self.assertFalse(record["trade_authorized"])
        self.assertEqual(self.snapshot(), before)

    def test_cli_blocked_capture_is_recorded_but_does_not_print_success_readiness(self):
        keys = self.save_keys()
        self.broker.fail_fills = True
        packet = self.packet()
        args = ["capture", "--data-dir", str(self.root), "--fire-id", self.fire_id,
                "--capture-key", str(keys["capture"]), "--output", str(self.root / "blocked.json")]
        with patch("tradebot.commissioning_review.DeltaDemo") as broker, \
                patch("tradebot.commissioning_review.capture_packet", return_value=packet), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(main(args), 2)
        self.assertIs(broker.call_args.kwargs["allow_orders"], False)
        message = json.loads(stdout.getvalue())
        self.assertFalse(message["ready_for_recovery_planning"])
        self.assertTrue(message["blockers"])
        self.assertFalse(message["lock_released"])


if __name__ == "__main__":
    unittest.main()
