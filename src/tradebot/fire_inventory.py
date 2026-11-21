"""Read-only local FIRE receipt inventory, without broker or AI access.

This is an evidence-coverage report, NOT account flatness, realized P&L,
trade profitability, or permission to execute a DEMO order. Never creates or
repairs the source databases. An exchange order can exist despite a local
no-order receipt; signed broker reconciliation is still required.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import stat

from tradebot.fire_performance import _validated

MARKET_DATABASES = {"BTCUSD": "fire-ops.sqlite", "XAUTUSD": "fire-xaut.sqlite"}
RECONCILIATION_DATABASE = "fire-reconciliation.sqlite"
CLOSED_RECEIPT_STATUSES = frozenset({"flat_verified", "aborted_flat", "cancelled_flat_verified"})
MAX_ROWS = 200_000
MAX_EXAMPLES = 200


class InventoryEvidenceError(ValueError):
    """Fixed diagnostic only, never raw SQLite contents."""


def _identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise InventoryEvidenceError("database_removed_during_read") from None
    except OSError:
        raise InventoryEvidenceError("database_unavailable") from None
    if not stat.S_ISREG(info.st_mode):
        raise InventoryEvidenceError("untrusted_database_path")
    return info.st_dev, info.st_ino


def _read_rows(path, query):
    """One SQLite read-only snapshot; fail if a source path changes identity."""
    if not path.exists() and not path.is_symlink():
        return None
    original = _identity(path)
    try:
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                                     uri=True, timeout=5)) as db:
            if _identity(path) != original:
                raise InventoryEvidenceError("database_replaced_during_read")
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise InventoryEvidenceError("database_integrity_failed")
            rows = db.execute(query + " LIMIT ?", (MAX_ROWS + 1,)).fetchall()
            if len(rows) > MAX_ROWS:
                raise InventoryEvidenceError("inventory_too_large")
            db.commit()
        if _identity(path) != original:
            raise InventoryEvidenceError("database_replaced_during_read")
        return rows
    except sqlite3.Error:
        raise InventoryEvidenceError("database_schema_or_read_failed") from None


def _timestamp(raw):
    if not isinstance(raw, str):
        raise InventoryEvidenceError("invalid_receipt_timestamp")
    try:
        instant = datetime.fromisoformat(raw)
    except ValueError:
        raise InventoryEvidenceError("invalid_receipt_timestamp") from None
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise InventoryEvidenceError("invalid_receipt_timestamp")
    return instant.timestamp()


def _receipt(symbol, row):
    press, created, updated, status, body = row
    if (not isinstance(press, str) or not re.fullmatch("[a-f0-9]{32}", press)
            or not isinstance(status, str)):
        raise InventoryEvidenceError("invalid_receipt_identity_or_status")
    start, stop = _timestamp(created), _timestamp(updated)
    if stop < start:
        raise InventoryEvidenceError("invalid_receipt_chronology")
    try:
        evidence = json.loads(body)
    except (TypeError, ValueError):
        raise InventoryEvidenceError("invalid_receipt_payload") from None
    if not isinstance(evidence, dict):
        raise InventoryEvidenceError("invalid_receipt_payload")
    submitted = evidence.get("orders_submitted")
    broker_refs = any(evidence.get(key) for key in (
        "broker_order_id", "entry", "exit_order_ids", "order_state", "protected_at"))
    protection_claimed = (evidence.get("protection_verified") is True
                          or evidence.get("liquidation_verified") is True)
    if (status == "rejected_no_order" and submitted is False
            and not broker_refs and not protection_claimed):
        category = "locally_reported_no_order"
    elif (status in CLOSED_RECEIPT_STATUSES and submitted is True
          and evidence.get("broker_order_id")):
        category = "locally_reported_flat"
    else:
        # Contradictory no-order claims or closed receipts without a linked
        # broker entry ID require review; never turn them into safe outcomes.
        category = "requires_broker_review"
    return {"symbol": symbol, "fire_id": press, "created_at": created,
            "updated_at": updated, "status": status, "category": category,
            "orders_submitted": submitted if type(submitted) is bool else None,
            "_created_sort": start}


def _financial_reviews(rows):
    """Classify latest local financial reports without exposing amounts.

    Shares the same per-snapshot financial consistency predicate as the
    performance summary. This proves at most the integrity of stored local
    reconciliation snapshots, never a current authenticated broker state.
    """
    grouped = defaultdict(list)
    for key, body in rows:
        if (not isinstance(key, str) or key.count(":") != 1
                or key.split(":")[0] not in MARKET_DATABASES
                or not re.fullmatch("[a-f0-9]{32}", key.split(":")[1])):
            raise InventoryEvidenceError("invalid_reconciliation_ownership")
        try:
            record = json.loads(body)
        except (TypeError, ValueError):
            raise InventoryEvidenceError("invalid_reconciliation_report") from None
        if not isinstance(record, dict):
            raise InventoryEvidenceError("invalid_reconciliation_report")
        grouped[key].append(record)

    statuses, verified = {}, {}
    for key, reports in grouped.items():
        cutoffs = [r.get("reconciliation_as_of_us") for r in reports]
        if any(type(v) is not int or v <= 0 for v in cutoffs):
            statuses[key] = "unsequenced_report"
            continue
        latest = max(cutoffs)
        newest = [r for r in reports if r["reconciliation_as_of_us"] == latest]
        try:
            canonical = {json.dumps(r, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False) for r in newest}
        except (ValueError, TypeError):
            statuses[key] = "invalid_latest_report"
            continue
        if len(canonical) != 1:
            statuses[key] = "conflicting_latest_reports"
            continue
        check = _validated(newest[0], key, latest)
        if check is None:
            statuses[key] = "latest_unverified_report"
            continue
        verified[key] = check
        statuses[key] = "latest_locally_verified_snapshot"

    # A duplicated broker fill or wallet posting cannot confirm two different
    # trades. Flag *all* conflicting owners rather than choosing a winner.
    owners = defaultdict(set)
    for key, entry in verified.items():
        for kind, values in (("fill", entry["fill_ids"]),
                             ("posting", entry["posting_ids"])):
            for identifier in values:
                owners[(kind, identifier)].add(key)
    for keys in owners.values():
        if len(keys) > 1:
            for key in keys:
                statuses[key] = "shared_broker_evidence_conflict"
    return statuses


def read_inventory(data_dir, *, limit=100):
    """Count every local FIRE receipt and reconcile *presence*, not economics.

    Snapshots are per database, not an atomic multi-file/broker transaction.
    Even a locally reported flat/no-order state is not current broker proof.
    """
    if type(limit) is not int or not 0 <= limit <= MAX_EXAMPLES:
        raise InventoryEvidenceError("invalid_example_limit")
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink():
        raise InventoryEvidenceError("untrusted_or_missing_data_directory")
    receipts = []
    by_market = {}
    missing = []
    for symbol, name in MARKET_DATABASES.items():
        rows = _read_rows(root / name,
                          "SELECT press,created_at,updated_at,status,result FROM fire_requests")
        if rows is None:
            missing.append(name)
            by_market[symbol] = {"receipt_database": "missing", "total_receipts": None}
            continue
        items = [_receipt(symbol, row) for row in rows]
        receipts.extend(items)
        by_market[symbol] = {
            "receipt_database": "present", "total_receipts": len(items),
        }

    report_rows = _read_rows(root / RECONCILIATION_DATABASE,
                             "SELECT trade_key,body FROM reports")
    known_keys = {r["symbol"] + ":" + r["fire_id"] for r in receipts}
    if report_rows is None:
        missing.append(RECONCILIATION_DATABASE)
        reviews = {}
    else:
        reviews = _financial_reviews(report_rows)
    review_keys = set(reviews)
    for item in receipts:
        key = item["symbol"] + ":" + item["fire_id"]
        item["local_financial_report_present"] = key in reviews
        item["local_financial_review_status"] = reviews.get(key, "no_report")
        if item["category"] == "locally_reported_no_order" and key in reviews:
            # A no-submission claim with a financial report is contradictory,
            # even when the report's own financial evidence is inconclusive.
            item["category"] = "requires_broker_review"

    # Recalculate after resolving cross-database contradictions; counts
    # collected before report inspection would otherwise undercount incidents.
    for symbol in MARKET_DATABASES:
        if by_market[symbol]["receipt_database"] != "present":
            continue
        counts = Counter(r["category"] for r in receipts if r["symbol"] == symbol)
        by_market[symbol].update({
            "locally_reported_no_order": counts["locally_reported_no_order"],
            "locally_reported_flat": counts["locally_reported_flat"],
            "requires_broker_review": counts["requires_broker_review"],
        })

    flat = [r for r in receipts if r["category"] == "locally_reported_flat"]
    missing_reviews = [r for r in flat if not r["local_financial_report_present"]]
    unverified_reviews = [r for r in flat
                          if r["local_financial_report_present"] and
                          r["local_financial_review_status"] != "latest_locally_verified_snapshot"]
    unresolved = [r for r in receipts if r["category"] == "requires_broker_review"]
    orphans = sorted(review_keys - known_keys)
    receipts.sort(key=lambda r: (r.pop("_created_sort"), r["symbol"], r["fire_id"]),
                  reverse=True)
    total = sum(x["total_receipts"] or 0 for x in by_market.values())
    evidence_complete = (not missing and not orphans and not unresolved
                         and not missing_reviews and not unverified_reviews)
    return {
        "mode": "read_only", "source": "local_fire_receipts_and_reconciliation_report_presence",
        "scope": "non_atomic_local_snapshots_not_current_broker_state",
        "trade_authorized": False, "broker_calls": 0, "ai_calls": 0,
        "is_account_flatness_verified": False, "is_account_realized_pnl": False,
        "financial_values_reported": False,
        "evidence_status": "inventory_complete_for_local_coverage_only"
            if evidence_complete else "incomplete_or_ambiguous",
        "missing_databases": missing,
        "by_market": by_market, "total_local_receipts": total,
        "locally_reported_flat_count": len(flat),
        "locally_reported_no_order_count": sum(
            r["category"] == "locally_reported_no_order" for r in receipts),
        "requires_broker_review_count": len(unresolved),
        "flat_receipts_missing_financial_review_count": len(missing_reviews),
        "flat_receipts_unverified_financial_review_count": len(unverified_reviews),
        "financial_review_status_counts": dict(sorted(Counter(reviews.values()).items())),
        "unmatched_financial_report_keys_count": len(orphans),
        "unmatched_financial_report_key_examples": orphans[:limit],
        "entries": receipts[:limit],
        "entries_truncated": len(receipts) > limit,
        "caveat": "Historical local verification is not fresh broker proof, current flatness or profitability",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        report = read_inventory(args.data_dir, limit=args.limit)
    except InventoryEvidenceError as exc:
        print(json.dumps({"mode": "read_only", "evidence_status": "unavailable",
                          "reason": str(exc), "trade_authorized": False}))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["evidence_status"] == "inventory_complete_for_local_coverage_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
