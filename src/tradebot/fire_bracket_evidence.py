"""Bounded, read-only historic bracket-field audit for one Delta India DEMO FIRE.

Compares saved FIRE order IDs with authenticated broker GET-by-ID responses.
This is NOT proof that the brackets were simultaneously active, that the
trade exited safely, that the account is flat, or authority to place orders.
"""
import argparse
import hashlib
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_broker_inventory import _read_local_snapshot, BrokerInventoryError
from tradebot.fire_inventory import MARKET_DATABASES

VALID_FIRE_ID = re.compile(r"[0-9a-f]{32}\Z")


class BracketEvidenceError(ValueError):
    """Only fixed failure codes, never private exchange payloads."""


def _id(raw):
    if type(raw) is int and raw > 0:
        return str(raw)
    if (type(raw) is str and 0 < len(raw) <= 32 and raw.isascii()
            and raw.isdecimal() and int(raw) > 0):
        return str(int(raw))
    raise BracketEvidenceError("invalid_local_broker_order_id")


def _size(raw):
    if type(raw) not in (str, int):
        raise BracketEvidenceError("invalid_contract_size")
    try:
        value = Decimal(str(raw))
    except (ValueError, InvalidOperation):
        raise BracketEvidenceError("invalid_contract_size") from None
    if not value.is_finite() or value != value.to_integral_value() or value <= 0:
        raise BracketEvidenceError("invalid_contract_size")
    return value


def _price(raw):
    if type(raw) not in (str, int):
        raise BracketEvidenceError("invalid_plan_price")
    try:
        value = Decimal(str(raw))
    except (ValueError, InvalidOperation):
        raise BracketEvidenceError("invalid_plan_price") from None
    if not value.is_finite() or value <= 0:
        raise BracketEvidenceError("invalid_plan_price")
    return value


def _source_snapshot(data_dir, symbol):
    """Fingerprint the *entire* bounded local FIRE ledger and file identity.

    The two read-only transactions cannot prevent concurrent writes, but a
    changed source must never produce a clean historical broker comparison.
    This ordinary SHA-256 is a local change detector, not a broker signature.
    """
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink():
        raise BracketEvidenceError("untrusted_local_data_directory")
    name = MARKET_DATABASES[symbol]
    try:
        identity, sections = _read_local_snapshot(root / name, name)
        encoded = json.dumps([identity, sections], sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).digest()
    except (BrokerInventoryError, OSError, ValueError, TypeError):
        raise BracketEvidenceError("local_fire_ledger_unverified") from None
    requests, _, entries = sections
    return requests, entries, fingerprint


def _saved(data_dir, symbol, fire_id):
    if symbol not in MARKET_DATABASES or not isinstance(fire_id, str) or \
            VALID_FIRE_ID.fullmatch(fire_id) is None:
        raise BracketEvidenceError("invalid_fire_identity")
    requests, entries, fingerprint = _source_snapshot(data_dir, symbol)
    found = [row for row in requests if row[0] == fire_id]
    if len(found) != 1:
        raise BracketEvidenceError("fire_receipt_not_found")
    try:
        data = json.loads(found[0][4])
    except (TypeError, ValueError):
        raise BracketEvidenceError("invalid_fire_receipt") from None
    if not isinstance(data, dict) or data.get("orders_submitted") is not True:
        raise BracketEvidenceError("no_submitted_order_receipt")
    if data.get("direction") not in ("LONG", "SHORT"):
        raise BracketEvidenceError("invalid_saved_direction")
    size = _size(data.get("contracts"))
    ids = data.get("exit_order_ids")
    if not isinstance(ids, dict) or set(ids) != {"stop_loss_order", "take_profit_order"}:
        raise BracketEvidenceError("missing_saved_protective_ids")
    parent = _id(data.get("broker_order_id"))
    stop, target = _id(ids["stop_loss_order"]), _id(ids["take_profit_order"])
    if len({parent, stop, target}) != 3:
        raise BracketEvidenceError("duplicate_saved_order_identity")
    # If durable entry receipt exists, it must agree on the selected parent
    # identity. No local record (or digest) can certify broker chronology.
    matching_entries = [row for row in entries if row[0] == fire_id]
    if len(matching_entries) > 1:
        raise BracketEvidenceError("conflicting_local_entry_receipts")
    if matching_entries:
        try:
            entry = json.loads(matching_entries[0][2])
            entry_parent = _id(entry.get("order_id"))
        except (TypeError, ValueError, AttributeError):
            raise BracketEvidenceError("invalid_local_entry_receipt") from None
        if entry_parent != parent:
            raise BracketEvidenceError("local_parent_order_identity_conflict")
    return ({
        "direction": data["direction"], "contracts": size,
        "stop_loss": _price(data.get("stop_loss")),
        "take_profit": _price(data.get("take_profit")),
        "parent": parent, "stop_loss_order": stop, "take_profit_order": target,
    }, fingerprint)


def _fetch_order(exchange, order_id):
    # Strict decimal ID: never interpolate an untrusted path fragment.
    reply = exchange._request("GET", "/v2/orders/" + order_id, auth=True)
    if not isinstance(reply, dict) or not isinstance(reply.get("result"), dict):
        raise BracketEvidenceError("broker_order_lookup_unverified")
    row = reply["result"]
    try:
        actual_id = _id(row.get("id"))
    except BracketEvidenceError:
        raise BracketEvidenceError("broker_order_identity_unverified") from None
    if actual_id != order_id:
        raise BracketEvidenceError("broker_order_identity_mismatch")
    return row


def audit_bracket_fields(exchange, data_dir, *, symbol, fire_id):
    """Never trades; a matching historical response is not a protection proof."""
    result = {
        "environment": "delta-india-demo", "mode": "read_only",
        "symbol": symbol if symbol in MARKET_DATABASES else None,
        "trade_authorized": False, "safe_to_enable_fire": False,
        "is_historical_protection_proven": False,
        "is_current_account_flatness_proven": False,
        "order_mutations": False, "ai_calls": 0,
        "authenticated_order_gets": 0,
        "local_evidence_stable_across_order_reads": False,
        "observation_status": "review_required", "blockers": [],
    }
    problems = result["blockers"]
    if getattr(exchange, "base_url", None) != DEMO_API or \
            getattr(exchange, "allow_orders", None) is not False:
        problems.append("read_only_delta_demo_client_required")
        return result
    try:
        saved, source_fingerprint = _saved(data_dir, symbol, fire_id)
    except BracketEvidenceError as exc:
        problems.append(str(exc))
        return result
    try:
        product_reply = exchange._request("GET", "/v2/products/" + symbol, auth=True)
        product = product_reply.get("result") if isinstance(product_reply, dict) else None
        pid = product.get("id") if isinstance(product, dict) else None
        if (not isinstance(product, dict) or product.get("symbol") != symbol
                or product.get("contract_type") != "perpetual_futures"
                or type(pid) is not int or pid <= 0):
            raise BracketEvidenceError("broker_product_unverified")
        parent = _fetch_order(exchange, saved["parent"])
        result["authenticated_order_gets"] += 1
        stop = _fetch_order(exchange, saved["stop_loss_order"])
        result["authenticated_order_gets"] += 1
        target = _fetch_order(exchange, saved["take_profit_order"])
        result["authenticated_order_gets"] += 1
    except BracketEvidenceError as exc:
        problems.append(str(exc))
        return result
    except Exception:
        # Never surface request errors (possibly containing API credentials).
        problems.append("authenticated_broker_order_read_unavailable")
        return result

    # Re-read the same original ledger after all four broker GETs. Without
    # this check, a changed FIRE receipt (or a replaced SQLite database)
    # could be compared against obsolete values yet reported as matching.
    try:
        _, _, after_fingerprint = _source_snapshot(data_dir, symbol)
    except BracketEvidenceError:
        problems.append("local_fire_evidence_changed_or_unavailable")
    else:
        if source_fingerprint != after_fingerprint:
            problems.append("local_fire_evidence_changed_during_broker_reads")
        else:
            result["local_evidence_stable_across_order_reads"] = True

    entry_side = "buy" if saved["direction"] == "LONG" else "sell"
    exit_side = "sell" if entry_side == "buy" else "buy"
    if (parent.get("product_id") != pid or parent.get("client_order_id") != fire_id
            or parent.get("side") != entry_side or parent.get("state") != "closed"
            or str(parent.get("unfilled_size")) not in ("0", "0.0", "0.00")):
        problems.append("broker_parent_fill_identity_or_state_unverified")
    try:
        if _size(parent.get("size")) != saved["contracts"]:
            problems.append("broker_parent_contract_size_mismatch")
    except BracketEvidenceError:
        problems.append("broker_parent_contract_size_unverified")

    child_states = {}
    for kind, order in (("stop_loss_order", stop), ("take_profit_order", target)):
        child_states[kind] = order.get("state") if order.get("state") in \
            ("open", "pending", "closed", "cancelled") else "unknown"
        expected_price = saved["stop_loss" if kind == "stop_loss_order"
                               else "take_profit"]
        if (order.get("product_id") != pid or order.get("side") != exit_side
                or order.get("stop_order_type") != kind
                or order.get("bracket_order") is not True):
            problems.append(kind + "_broker_identity_unverified")
        try:
            if _size(order.get("size")) != saved["contracts"]:
                problems.append(kind + "_broker_contract_size_mismatch")
        except BracketEvidenceError:
            problems.append(kind + "_broker_contract_size_unverified")
        try:
            if _price(order.get("stop_price")) != expected_price:
                problems.append(kind + "_broker_trigger_mismatch")
        except BracketEvidenceError:
            problems.append(kind + "_broker_trigger_unverified")
        if child_states[kind] == "unknown":
            problems.append(kind + "_broker_state_unverified")
    result["historical_child_states"] = child_states
    result["blockers"] = sorted(set(problems))
    if not result["blockers"]:
        result["observation_status"] = "historical_order_fields_match_not_protection_proof"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    parser.add_argument("--symbol", required=True, choices=sorted(MARKET_DATABASES))
    parser.add_argument("--fire-id", required=True)
    args = parser.parse_args(argv)
    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    report = audit_bracket_fields(
        exchange, args.data_dir, symbol=args.symbol, fire_id=args.fire_id
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["observation_status"] == \
        "historical_order_fields_match_not_protection_proof" else 2


if __name__ == "__main__":
    raise SystemExit(main())
