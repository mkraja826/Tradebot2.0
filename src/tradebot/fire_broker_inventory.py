"""Read-only Delta DEMO account-exposure observations cross-checked with FIRE receipts.

Two authenticated GET sweeps separated by at least 11 elapsed seconds.
This is an operator diagnostic ONLY: never authority to open a trade, restart
a service, clear an emergency lock or claim complete historical broker fills.
The Delta margined endpoint can lag; filtered real-time BTC/Gold positions
are inspected independently. A zero snapshot does not prove ongoing flatness.
"""
import argparse
import hashlib
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_inventory import (
    read_inventory, InventoryEvidenceError, MARKET_DATABASES,
    RECONCILIATION_DATABASE, MAX_ROWS, _identity,
)
from tradebot.demo_upgrade_preflight import SAFE_TERMINAL

SYMBOLS = ("BTCUSD", "XAUTUSD")
SAMPLE_INTERVAL_SECONDS = 11
MAX_SWEEP_SECONDS = 90
MAX_PAGES = 100


class BrokerInventoryError(ValueError):
    """Sanitized evidence-failure code, never provider response content."""


def _quantity(raw):
    if type(raw) not in (str, int, Decimal):
        raise BrokerInventoryError("invalid_position_size")
    try:
        value = Decimal(str(raw))
    except (ValueError, TypeError, InvalidOperation):
        raise BrokerInventoryError("invalid_position_size") from None
    if not value.is_finite() or value != value.to_integral_value():
        raise BrokerInventoryError("invalid_position_size")
    return value


def _product_id(raw):
    if type(raw) is int and raw > 0:
        return raw
    if type(raw) is str and raw.isdecimal() and int(raw) > 0:
        return int(raw)
    raise BrokerInventoryError("unidentified_broker_product")


def _order_id(raw):
    if type(raw) not in (str, int) or not str(raw).strip():
        raise BrokerInventoryError("unidentified_open_order")
    return str(raw)


def _get(exchange, path, *, params=None):
    reply = exchange._request("GET", path, params=params, auth=True)
    if not isinstance(reply, dict):
        raise BrokerInventoryError("invalid_authenticated_response")
    return reply


def _all_open_orders(exchange):
    """Inspect every account order page. Missing pagination metadata fails shut."""
    orders, cursor, seen = {}, None, set()
    for _ in range(MAX_PAGES):
        params = {"states": "open,pending", "page_size": 50}
        if cursor is not None:
            params["after"] = cursor
        result = _get(exchange, "/v2/orders", params=params)
        rows, meta = result.get("result"), result.get("meta")
        if (not isinstance(rows, list) or len(rows) > 50
                or any(not isinstance(v, dict) for v in rows)
                or not isinstance(meta, dict) or "after" not in meta):
            raise BrokerInventoryError("open_orders_pagination_unverified")
        for row in rows:
            oid = _order_id(row.get("id"))
            _product_id(row.get("product_id"))
            if oid in orders and orders[oid] != row:
                raise BrokerInventoryError("conflicting_broker_order_identity")
            orders[oid] = row
        nxt = meta["after"]
        if nxt in (None, ""):
            return len(orders)
        if not isinstance(nxt, str) or nxt in seen or nxt == cursor:
            raise BrokerInventoryError("open_orders_pagination_unverified")
        seen.add(nxt)
        cursor = nxt
    raise BrokerInventoryError("open_orders_pagination_unverified")


def _positions_for_product(exchange, pid):
    rows = _get(exchange, "/v2/positions", params={"product_id": pid}).get("result")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise BrokerInventoryError("realtime_position_unverified")
    values = []
    for row in rows:
        if not isinstance(row, dict) or _product_id(row.get("product_id", pid)) != pid:
            raise BrokerInventoryError("realtime_position_unverified")
        values.append(_quantity(row.get("size")))
    if sum(v != 0 for v in values) > 1:
        raise BrokerInventoryError("multiple_realtime_positions")
    return str(sum(values, Decimal(0)))


def _sample(exchange):
    """Authenticated unfiltered margin, full open orders and two real-time markets."""
    profile = _get(exchange, "/v2/profile").get("result")
    if not isinstance(profile, dict):
        raise BrokerInventoryError("account_profile_unverified")
    isolated = profile.get("margin_mode") == "isolated"

    wide = _get(exchange, "/v2/positions/margined")
    rows = wide.get("result")
    if not isinstance(rows, list):
        raise BrokerInventoryError("account_positions_unverified")
    # A broker-supplied pagination cursor cannot be ignored.
    meta = wide.get("meta")
    if meta is not None and (
            not isinstance(meta, dict) or meta.get("after") not in (None, "")):
        raise BrokerInventoryError("account_positions_pagination_unverified")
    active = []
    by_product = Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise BrokerInventoryError("account_positions_unverified")
        pid = _product_id(row.get("product_id"))
        size = _quantity(row.get("size"))
        if size:
            active.append(pid)
            by_product[pid] += 1
    if any(count > 1 for count in by_product.values()):
        raise BrokerInventoryError("multiple_margined_positions")

    open_orders = _all_open_orders(exchange)
    realtime = {}
    product_ids = {}
    for symbol in SYMBOLS:
        product = _get(exchange, "/v2/products/" + symbol).get("result")
        if (not isinstance(product, dict) or product.get("symbol") != symbol
                or product.get("contract_type") != "perpetual_futures"):
            raise BrokerInventoryError("fire_product_unverified")
        pid = _product_id(product.get("id"))
        if pid in product_ids.values():
            raise BrokerInventoryError("fire_product_identity_conflict")
        product_ids[symbol] = pid
        realtime[symbol] = _positions_for_product(exchange, pid)
    return {
        "isolated_margin_observed": isolated,
        "account_margined_nonzero_positions": len(active),
        "account_open_orders": open_orders,
        "realtime_fire_sizes": realtime,
        "fire_product_ids": product_ids,
        # Do not expose raw account/order IDs or individual balances in output.
        "margined_fire_consistency": all(
            (product_ids[symbol] in active) == (Decimal(size) != 0)
            for symbol, size in realtime.items()),
    }


def _read_local_snapshot(path, name):
    """One bounded, read-only SQLite transaction per source database.

    Check device/inode before and after the transaction. Unlike separate
    connections for individual tables, all SELECTs share one consistent
    SQLite read snapshot, including the schema and entry-intent rows.
    """
    initial = _identity(path)
    try:
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                                     uri=True, timeout=5)) as db:
            if _identity(path) != initial:
                raise BrokerInventoryError("local_ledger_changed_during_read")
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise BrokerInventoryError("local_ledger_integrity_unverified")

            def select(query):
                rows = db.execute(query + " LIMIT ?", (MAX_ROWS + 1,)).fetchall()
                if len(rows) > MAX_ROWS:
                    raise BrokerInventoryError("local_ledger_too_large")
                return rows

            if name == RECONCILIATION_DATABASE:
                reports = select("SELECT digest,trade_key,body FROM reports ORDER BY digest")
                tables = select("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name IN ('evidence','claims') ORDER BY name")
                present = {row[0] for row in tables}
                if reports and present != {"evidence", "claims"}:
                    raise BrokerInventoryError("reconciliation_source_tables_missing")
                source = [select("SELECT kind,id,body FROM evidence ORDER BY kind,id")
                          if table == "evidence" else
                          select("SELECT kind,id,trade_key FROM claims ORDER BY kind,id")
                          for table in ("evidence", "claims") if table in present]
                results = [reports, tables, *source]
            else:
                requests = select("SELECT press,created_at,updated_at,status,result "
                                  "FROM fire_requests ORDER BY press")
                tables = select("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name='fire_entries'")
                entries = (select("SELECT press,status,receipt FROM fire_entries ORDER BY press")
                           if tables else [])
                results = [requests, tables, entries]
            db.commit()
        if _identity(path) != initial:
            raise BrokerInventoryError("local_ledger_changed_during_read")
        return initial, results
    except sqlite3.Error:
        raise BrokerInventoryError("local_evidence_or_entry_states_unverified") from None


def _check_reconciliation_links(results):
    """Reject dangling source/claim references in one SQLite read snapshot.

    This is a structural check against the local append-only writer's layout,
    not exchange authentication or proof that source events are complete.
    """
    reports, tables, *source = results
    present = {row[0] for row in tables}
    if present != {"evidence", "claims"}:
        if reports or source:
            raise BrokerInventoryError("reconciliation_source_tables_missing")
        return

    if len(source) != 2:
        raise BrokerInventoryError("reconciliation_source_tables_missing")
    evidence_rows, claim_rows = source
    available = set()
    for kind, identifier, body in evidence_rows:
        if (kind not in ("fill", "posting") or type(identifier) is not str
                or not identifier or type(body) is not str):
            raise BrokerInventoryError("invalid_reconciliation_source_identity")
        try:
            parsed = json.loads(body)
        except (TypeError, ValueError):
            raise BrokerInventoryError("invalid_reconciliation_source_body") from None
        if (not isinstance(parsed, dict) or
                type(parsed.get("id")) not in (str, int) or
                str(parsed["id"]) != identifier):
            raise BrokerInventoryError("reconciliation_source_id_mismatch")
        available.add((kind, identifier))

    claims = {}
    for kind, identifier, trade_key in claim_rows:
        if ((kind, identifier) not in available or
                type(trade_key) is not str or not trade_key):
            raise BrokerInventoryError("dangling_reconciliation_claim")
        claims[(kind, identifier)] = trade_key

    verified_claims = set()
    for _, trade_key, body in reports:
        try:
            report = json.loads(body)
        except (ValueError, TypeError):
            raise BrokerInventoryError("invalid_reconciliation_report_body") from None
        if not isinstance(report, dict):
            raise BrokerInventoryError("invalid_reconciliation_report_body")
        if report.get("is_net_realized_pnl") is not True:
            continue
        for kind, field in (("fill", "matched_fill_ids"),
                            ("posting", "matched_posting_ids")):
            ids = report.get(field)
            if (not isinstance(ids, list) or not ids or
                    any(type(v) not in (str, int) or not str(v) for v in ids)):
                raise BrokerInventoryError("verified_report_source_ids_missing")
            for identifier in ids:
                key = (kind, str(identifier))
                if key not in available or claims.get(key) != trade_key:
                    raise BrokerInventoryError("verified_report_claim_unmatched")
                verified_claims.add(key)

    if set(claims) - verified_claims:
        raise BrokerInventoryError("orphan_reconciliation_claim")


def _local_evidence_state(data_dir):
    """Fingerprint single-transaction source snapshots and durable entry intent.

    Each database has one consistent local SQLite snapshot, but there is no
    cross-database or broker/database atomic transaction. Fingerprints stay
    internal and are never a broker authenticity claim.
    """
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink():
        raise BrokerInventoryError("local_data_directory_untrusted")
    evidence = hashlib.sha256()
    unresolved = 0
    valid_parent = SAFE_TERMINAL | {
        "requested", "reasoning", "preflight", "submitting",
        "reconciling", "verifying_protection", "protected_active",
        "exposure_unknown",
    }
    valid_entry = {"submitting", "unconfirmed", "accepted",
                   "filled", "cancelled", "flat_verified"}
    try:
        for name in (*MARKET_DATABASES.values(), RECONCILIATION_DATABASE):
            identity, results = _read_local_snapshot(root / name, name)
            if name == RECONCILIATION_DATABASE:
                _check_reconciliation_links(results)
            else:
                requests, _, entries = results
                parents = {}
                unresolved_presses = set()
                for press, _, _, status, _ in requests:
                    if (type(press) is not str or not press
                            or type(status) is not str or status not in valid_parent):
                        raise BrokerInventoryError("unverified_parent_fire_state")
                    parents[press] = status
                    if status not in SAFE_TERMINAL:
                        unresolved_presses.add(press)
                for press, status, _ in entries:
                    if (type(press) is not str or press not in parents
                            or type(status) is not str or status not in valid_entry):
                        raise BrokerInventoryError("orphan_or_unverified_entry_state")
                    if parents[press] == "rejected_no_order":
                        raise BrokerInventoryError("no_order_receipt_has_durable_entry")
                    if status in ("submitting", "unconfirmed", "accepted"):
                        unresolved_presses.add(press)
                unresolved += len(unresolved_presses)
            encoded = json.dumps([name, identity, results], sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)
            evidence.update(encoded.encode("utf-8"))
        return evidence.digest(), unresolved
    except BrokerInventoryError:
        raise
    except (InventoryEvidenceError, ValueError, TypeError, OSError):
        raise BrokerInventoryError("local_evidence_or_entry_states_unverified") from None

def observe_broker_inventory(exchange, data_dir, *, pause=time.sleep,
                             monotonic=time.monotonic):
    """Return a bounded diagnostic. Failures are safely attributed and never green."""
    report = {
        "environment": "delta-india-demo", "mode": "read_only",
        "trade_authorized": False, "safe_to_enable_fire": False,
        "is_account_flatness_verified_for_future_orders": False,
        "is_complete_broker_trade_history": False,
        "is_account_realized_pnl": False, "ai_calls": 0, "order_mutations": False,
        "samples_checked": 0, "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "sample_interval_verified": False,
        "broker_positions_last": None, "broker_open_orders_last": None,
        "realtime_fire_sizes_last": None, "local_evidence_status": "unavailable",
        "observation_status": "blocked_or_unverified", "blockers": [],
    }
    blockers = report["blockers"]
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(
            exchange, "allow_orders", None) is not False:
        blockers.append("read_only_delta_demo_client_required")
        return report
    if not callable(pause) or not callable(monotonic):
        blockers.append("invalid_observation_clock")
        return report
    try:
        original = read_inventory(data_dir, limit=0)
        report["local_evidence_status"] = original["evidence_status"]
        report["local_receipts_total"] = original["total_local_receipts"]
        report["local_requires_broker_review_count"] = original["requires_broker_review_count"]
        if original["evidence_status"] != "inventory_complete_for_local_coverage_only":
            blockers.append("local_history_incomplete_or_ambiguous")
        if original["missing_databases"]:
            # Keep the precise previous diagnostic and never make broker
            # requests when an expected local receipt ledger is absent.
            return report
        original_fingerprint, unresolved_entries = _local_evidence_state(data_dir)
        report["local_unresolved_entry_intents"] = unresolved_entries
        if unresolved_entries:
            blockers.append("unresolved_local_fire_entries")
    except (InventoryEvidenceError, BrokerInventoryError, OSError, ValueError):
        blockers.append("local_history_unavailable")
        return report

    snapshots = []
    for index in range(2):
        try:
            if index:
                pause(SAMPLE_INTERVAL_SECONDS)
                delay = monotonic() - previous_end
                if (not isinstance(delay, (int, float)) or
                        not math.isfinite(delay) or delay < SAMPLE_INTERVAL_SECONDS):
                    blockers.append("sample_spacing_not_verified")
                    break
                report["sample_interval_verified"] = True
            started = monotonic()
            if not isinstance(started, (int, float)) or not math.isfinite(started):
                raise BrokerInventoryError("observation_clock_unverified")
            item = _sample(exchange)
            elapsed = monotonic() - started
            if (not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed)
                    or elapsed < 0 or elapsed > MAX_SWEEP_SECONDS):
                raise BrokerInventoryError("broker_sample_timing_unverified")
            snapshots.append(item)
            report["samples_checked"] += 1
            previous_end = monotonic()
        except BrokerInventoryError as exc:
            blockers.append(exc.args[0])
            break
        except Exception:
            blockers.append("authenticated_broker_read_unavailable")
            break

    if snapshots:
        last = snapshots[-1]
        report["broker_positions_last"] = last["account_margined_nonzero_positions"]
        report["broker_open_orders_last"] = last["account_open_orders"]
        report["realtime_fire_sizes_last"] = last["realtime_fire_sizes"]
    if len(snapshots) == 2:
        if snapshots[0]["fire_product_ids"] != snapshots[1]["fire_product_ids"]:
            blockers.append("fire_product_changed_between_samples")
        for item in snapshots:
            if not item["isolated_margin_observed"]:
                blockers.append("account_isolated_margin_unverified")
            if item["account_margined_nonzero_positions"]:
                blockers.append("account_has_exposure")
            if item["account_open_orders"]:
                blockers.append("account_has_open_orders")
            if any(Decimal(size) != 0 for size in item["realtime_fire_sizes"].values()):
                blockers.append("fire_market_has_exposure")
            if not item["margined_fire_consistency"]:
                blockers.append("lagging_or_inconsistent_broker_positions")
        if snapshots[0] != snapshots[1]:
            blockers.append("broker_inventory_changed_between_samples")
    else:
        blockers.append("two_broker_samples_unavailable")

    try:
        final = read_inventory(data_dir, limit=0)
        final_fingerprint, final_unresolved_entries = _local_evidence_state(data_dir)
        if final != original or final_fingerprint != original_fingerprint or \
                final_unresolved_entries != unresolved_entries:
            blockers.append("local_evidence_changed_during_broker_observation")
    except (InventoryEvidenceError, BrokerInventoryError, OSError, ValueError):
        blockers.append("local_evidence_changed_or_unavailable")
    report["blockers"] = sorted(set(blockers))
    if not report["blockers"]:
        report["observation_status"] = "two_flat_snapshots_observed_not_trade_authority"
    report["as_of_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    args = parser.parse_args(argv)
    broker = DeltaDemo(api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
                       api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""), allow_orders=False)
    report = observe_broker_inventory(broker, args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["observation_status"] == "two_flat_snapshots_observed_not_trade_authority" else 2


if __name__ == "__main__":
    raise SystemExit(main())
