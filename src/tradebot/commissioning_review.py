"""Signed, read-only Gold recovery evidence and separate operator review.

There is deliberately no execution, lock-release or leverage-setting command.
Signatures are LOCAL attestations of authenticated DEMO reads, not exchange
signatures. Trust requires separately pinned capture and operator public keys.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_commission_preflight import commissioning_preflight
from tradebot.portfolio_equity_guard import stamp

LOCK_NAME = "gold-demo-commission-attempt.lock"
PACKET_SCHEMA = "gold-demo-recovery-evidence-v1"
REVIEW_SCHEMA = "gold-demo-recovery-review-v1"
MAX_REVIEW_AGE_US = 120_000_000
MAX_FILE_BYTES = 262144
PREFLIGHT_FLAGS = ("ready_for_supervised_operator_review", "broker_flat_two_samples",
                   "both_fire_endpoints_disabled", "watchdog_and_dashboard_active",
                   "equity_prerequisites_verified")


class ReviewError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ReviewError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _read_file(path, *, private=False):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE_BYTES, "invalid_evidence_file")
        if private:
            require(info.st_mode & 0o077 == 0, "private_file_permissions_required")
        content = file.read(MAX_FILE_BYTES + 1)
        after = os.fstat(file.fileno())
        require(len(content) <= MAX_FILE_BYTES and info.st_mtime_ns == after.st_mtime_ns
                and info.st_size == after.st_size, "evidence_changed_during_read")
    return content, info


def _public_hex(key):
    if isinstance(key, Ed25519PrivateKey):
        key = key.public_key()
    require(isinstance(key, Ed25519PublicKey), "ed25519_key_required")
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def load_key(path, *, private=False):
    raw, _ = _read_file(path, private=private)
    try:
        key = (serialization.load_pem_private_key(raw, password=None) if private else
               serialization.load_pem_public_key(raw))
    except (ValueError, TypeError):
        raise ReviewError("invalid_signing_key") from None
    require(isinstance(key, Ed25519PrivateKey if private else Ed25519PublicKey), "ed25519_key_required")
    return key


def seal(payload, key):
    require(isinstance(key, Ed25519PrivateKey), "private_signing_key_required")
    return {"payload":payload, "public_key":_public_hex(key),
            "signature":key.sign(canonical(payload)).hex()}


def verify(envelope, trusted_key, schema):
    require(isinstance(trusted_key, Ed25519PublicKey), "trusted_public_key_required")
    require(isinstance(envelope, dict) and set(envelope) == {"payload","public_key","signature"},
            "invalid_signed_envelope")
    require(envelope["public_key"] == _public_hex(trusted_key), "untrusted_signer")
    require(isinstance(envelope["payload"], dict) and envelope["payload"].get("schema") == schema,
            "invalid_packet_schema")
    require(isinstance(envelope["signature"], str) and re.fullmatch(r"[0-9a-f]{128}", envelope["signature"]),
            "invalid_signature")
    try:
        trusted_key.verify(bytes.fromhex(envelope["signature"]), canonical(envelope["payload"]))
    except (InvalidSignature, ValueError, TypeError):
        raise ReviewError("invalid_signature") from None
    return envelope["payload"]


def write_exclusive(path, envelope):
    """Never overwrite evidence, locks, receipts or keys; partial writes fail shut."""
    content = canonical(envelope) + b"\n"
    require(len(content) <= MAX_FILE_BYTES, "packet_too_large")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,"O_NOFOLLOW",0), 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    directory = os.open(Path(path).parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _instant(value):
    try:
        return stamp(datetime.fromisoformat(value))
    except (ValueError, TypeError, OverflowError):
        raise ReviewError("invalid_attempt_timestamp") from None


def _rows_digest(db, query):
    """Bind the receipt/entry inventory without copying private payloads out."""
    evidence = hashlib.sha256()
    for row in db.execute(query):
        evidence.update(canonical(list(row)) + b"\n")
    return evidence.hexdigest()


def attempt_evidence(data_dir, fire_id):
    """Read the exact latest Gold attempt and consumed lock without migrations."""
    require(isinstance(fire_id, str) and re.fullmatch(r"[0-9a-f]{32}", fire_id), "invalid_fire_id")
    root = Path(data_dir)
    require(root.is_dir() and not root.is_symlink(), "existing_trusted_data_directory_required")
    lock, info = _read_file(root / LOCK_NAME)
    lock_proof = {"sha256":hashlib.sha256(lock).hexdigest(), "size":info.st_size,
                  "mtime_ns":info.st_mtime_ns, "inode":info.st_ino, "device":info.st_dev}
    path = root / "fire-xaut.sqlite"
    require(path.is_file() and not path.is_symlink(), "existing_gold_receipt_database_required")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        require(db.execute("PRAGMA quick_check(1)").fetchone() == ("ok",), "receipt_database_integrity_failed")
        row = db.execute("SELECT press,created_at,updated_at,status,result FROM fire_requests "
                         "WHERE press=?", (fire_id,)).fetchone()
        require(row is not None, "prior_fire_receipt_missing")
        latest = db.execute("SELECT press FROM fire_requests WHERE created_at>=?", (row[1],)).fetchall()
        require(latest == [(fire_id,)], "prior_attempt_is_not_latest_gold_request")
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fire_entries'").fetchone()
        entry = db.execute("SELECT status,receipt FROM fire_entries WHERE press=?", (fire_id,)).fetchone() if exists else None
        request_inventory = _rows_digest(db, "SELECT press,created_at,updated_at,status,result "
                                            "FROM fire_requests ORDER BY press")
        entry_inventory = (_rows_digest(db, "SELECT press,status,receipt FROM fire_entries ORDER BY press")
                           if exists else None)
    result = json.loads(row[4])
    require(isinstance(result, dict), "invalid_prior_receipt")
    created, updated = _instant(row[1]), _instant(row[2])
    require(0 < created <= updated, "invalid_attempt_timestamp")
    reason = result.get("reason_code")
    reason = reason if isinstance(reason,str) and re.fullmatch(r"[a-z0-9_]{1,100}",reason) else "unclassified"
    prior = {
        "fire_id":fire_id, "status":row[3], "created_us":created, "updated_us":updated,
        "orders_submitted":result.get("orders_submitted") is True,
        "orders_explicitly_not_submitted":result.get("orders_submitted") is False,
        "entry_intent_present":entry is not None,
        "broker_order_references_present":any(result.get(key) is not None for key in
            ("broker_order_id", "exit_order_ids", "entry", "order_state", "protected_at"))
            or result.get("protection_verified") is True or result.get("liquidation_verified") is True,
        "reason_code":reason, "request_sha256":digest(list(row)),
        "entry_sha256":digest(list(entry)) if entry else None,
        "request_inventory_sha256":request_inventory, "entry_inventory_sha256":entry_inventory,
        "lock_correlated_with_attempt":-5_000_000 <= created - info.st_mtime_ns // 1000 <= 120_000_000,
        "lock":lock_proof,
    }
    return prior


def _eligible_prior(prior):
    return (isinstance(prior, dict) and prior.get("status") == "rejected_no_order"
            and prior.get("orders_explicitly_not_submitted") is True
            and prior.get("orders_submitted") is False
            and prior.get("entry_intent_present") is False
            and prior.get("broker_order_references_present") is False
            and prior.get("lock_correlated_with_attempt") is True)


def _eligible_preflight(gate):
    return (isinstance(gate, dict) and all(gate.get(k) is True for k in PREFLIGHT_FLAGS)
            and gate.get("trade_authorized") is False and gate.get("blockers") == [])


def capture_packet(exchange, data_dir, fire_id, capture_key, *, readiness=commissioning_preflight,
                   now=None):
    require(getattr(exchange,"base_url",None) == DEMO_API and getattr(exchange,"allow_orders",None) is False,
            "read_only_demo_client_required")
    started_us = stamp(now or datetime.now(timezone.utc))
    monotonic_start = time.monotonic_ns()
    prior = attempt_evidence(data_dir, fire_id)
    blockers = []
    if not (prior["status"] == "rejected_no_order" and prior["orders_explicitly_not_submitted"]
            and not prior["entry_intent_present"] and not prior["broker_order_references_present"]):
        blockers.append("prior_attempt_requires_full_fill_and_order_reconciliation")
    if not prior["lock_correlated_with_attempt"]:
        blockers.append("commissioning_lock_not_correlated_with_attempt")
    gate = readiness(exchange, data_dir)
    require(isinstance(gate, dict), "invalid_readiness_report")
    if not _eligible_preflight(gate):
        blockers.append("commissioning_prerequisites_incomplete")
    history = {"verified":False, "fill_count":None}
    if prior["updated_us"] + 300_000_000 > started_us:
        blockers.append("prior_attempt_settlement_window_not_ready")
    else:
        try:
            product = exchange._request("GET", "/v2/products/XAUTUSD")["result"]
            require(product.get("symbol") == "XAUTUSD" and product.get("contract_type") == "perpetual_futures"
                    and type(product.get("id")) is int and product["id"] > 0, "gold_product_unverified")
            start_us, end_us = prior["created_us"] - 1_000_000, prior["updated_us"] + 60_000_000
            fills = exchange.product_fills(product["id"], start_time_us=start_us, end_time_us=end_us)
            require(isinstance(fills, list), "fill_history_unavailable")
            history = {"verified":True, "product_id":product["id"], "start_us":start_us, "end_us":end_us,
                       "fill_count":len(fills), "response_sha256":digest(fills),
                       "no_fills_in_attempt_window":fills == []}
            if fills:
                blockers.append("broker_fills_exist_in_attempt_window")
        except Exception:
            blockers.append("historical_broker_fills_not_verified")
    require(attempt_evidence(data_dir, fire_id) == prior, "local_evidence_changed_during_capture")
    captured_us = stamp(now or datetime.now(timezone.utc))
    elapsed_us = (time.monotonic_ns() - monotonic_start) // 1000
    require(0 <= captured_us - started_us <= MAX_REVIEW_AGE_US
            and 0 <= elapsed_us <= MAX_REVIEW_AGE_US
            and abs(captured_us - started_us - elapsed_us) <= 1_000_000,
            "capture_too_slow_or_clock_inconsistent")
    payload = {
        "schema":PACKET_SCHEMA, "environment":"delta-india-demo", "symbol":"XAUTUSD",
        "started_us":started_us, "captured_us":captured_us, "elapsed_us":elapsed_us,
        "signature_scope":"local_attestation_of_authenticated_demo_reads",
        "prior_attempt":prior, "historical_fills":history, "preflight":gate,
        "blockers":blockers, "ready_for_recovery_planning":not blockers,
        "trade_authorized":False, "lock_released":False, "orders_submitted":False,
        "separate_recovery_and_execution_approval_required":True,
    }
    return seal(payload, capture_key)


def review_packet(envelope, trusted_capture_key, operator_key, data_dir, *, decision, now=None):
    payload = verify(envelope, trusted_capture_key, PACKET_SCHEMA)
    require(_public_hex(operator_key) != _public_hex(trusted_capture_key), "separate_operator_key_required")
    require(decision in {"accept_for_recovery_planning","reject"}, "invalid_review_decision")
    reviewed_us = stamp(now or datetime.now(timezone.utc))
    require(payload.get("environment") == "delta-india-demo" and payload.get("symbol") == "XAUTUSD"
            and payload.get("trade_authorized") is False and payload.get("lock_released") is False
            and payload.get("orders_submitted") is False
            and payload.get("signature_scope") == "local_attestation_of_authenticated_demo_reads"
            and payload.get("separate_recovery_and_execution_approval_required") is True,
            "invalid_review_scope")
    if decision == "accept_for_recovery_planning":
        require(type(payload.get("started_us")) is int and type(payload.get("captured_us")) is int
                and 0 < payload["started_us"] <= payload["captured_us"] <= reviewed_us
                and type(payload.get("elapsed_us")) is int and 0 <= payload["elapsed_us"] <= MAX_REVIEW_AGE_US
                and abs(payload["captured_us"] - payload["started_us"] - payload["elapsed_us"]) <= 1_000_000
                and reviewed_us - payload["started_us"] <= MAX_REVIEW_AGE_US, "stale_or_future_capture")
        prior = payload.get("prior_attempt")
        history = payload.get("historical_fills")
        require(payload.get("ready_for_recovery_planning") is True and payload.get("blockers") == []
                and _eligible_preflight(payload.get("preflight")) and _eligible_prior(prior)
                and isinstance(history, dict) and history.get("verified") is True
                and type(history.get("product_id")) is int and history["product_id"] > 0
                and history.get("no_fills_in_attempt_window") is True
                and type(history.get("fill_count")) is int and history["fill_count"] == 0
                and history.get("response_sha256") == digest([]), "blocked_recovery_evidence")
        require(attempt_evidence(data_dir, prior["fire_id"]) == prior, "local_evidence_changed_since_capture")
        require(history.get("start_us") == prior["created_us"] - 1_000_000
                and history.get("end_us") == prior["updated_us"] + 60_000_000
                and prior["updated_us"] + 300_000_000 <= payload["started_us"],
                "invalid_historical_window")
    return seal({"schema":REVIEW_SCHEMA, "packet_sha256":digest(envelope), "decision":decision,
                 "reviewed_us":reviewed_us, "trade_authorized":False, "lock_released":False,
                 "separate_recovery_and_execution_approval_required":True}, operator_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="Create a signed read-only evidence packet")
    capture.add_argument("--data-dir", required=True)
    capture.add_argument("--fire-id", required=True)
    capture.add_argument("--capture-key", required=True)
    capture.add_argument("--output", required=True)
    review = sub.add_parser("review", help="Record an operator planning decision; never unlock")
    review.add_argument("--data-dir", required=True)
    review.add_argument("--packet", required=True)
    review.add_argument("--trusted-capture-key", required=True)
    review.add_argument("--operator-key", required=True)
    review.add_argument("--decision", choices=("accept_for_recovery_planning","reject"), required=True)
    review.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            key = load_key(args.capture_key, private=True)
            exchange = DeltaDemo(api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
                                 api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""), allow_orders=False)
            envelope = capture_packet(exchange, args.data_dir, args.fire_id, key)
        else:
            raw, _ = _read_file(args.packet, private=True)
            envelope = review_packet(json.loads(raw), load_key(args.trusted_capture_key),
                                     load_key(args.operator_key, private=True), args.data_dir, decision=args.decision)
        write_exclusive(args.output, envelope)
    except (ValueError, TypeError, OSError, sqlite3.Error, KeyError):
        print(json.dumps({"status":"blocked_or_unverified", "trade_authorized":False,
                          "lock_released":False, "action":"operator_evidence_review_required"}))
        return 2
    print(json.dumps({"status":"signed_record_created", "sha256":digest(envelope),
                      "ready_for_recovery_planning":envelope["payload"].get("ready_for_recovery_planning", False),
                      "decision":envelope["payload"].get("decision"),
                      "blockers":envelope["payload"].get("blockers", []),
                      "trade_authorized":False, "lock_released":False}))
    if args.command == "capture" and not envelope["payload"]["ready_for_recovery_planning"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
