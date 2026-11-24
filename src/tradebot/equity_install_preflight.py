"""No-write, no-broker equity collector unit-install schema preflight.

A schema pass is only permission to REQUEST an approved unit-staging change.
It cannot certify historical receipts, daily/weekly openings, or trade safety.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from tradebot.equity_policy_core import EquityRiskError, validated_watermark

REQUIRED_TABLES = frozenset((
    "equity_evidence", "equity_watermark", "equity_read_receipts",
))
IMMUTABLE_TRIGGERS = frozenset((
    "reject_equity_evidence_update",
    "reject_equity_evidence_replace",
    "reject_equity_receipt_replace",
    "reject_equity_receipt_update",
    "reject_equity_receipt_delete",
    "reject_equity_evidence_delete",
))


def inspect_collector_schema(data_dir):
    """Never create, modify or migrate a ledger and never grant FIRE permission."""
    report = {
        "mode": "read_only_collector_install_preflight",
        "status": "blocked",
        "reason": "existing_ledger_unavailable",
        "ledger_integrity_verified": False,
        "receipt_schema_present": False,
        "immutable_triggers_present": False,
        "preserved_watermark_consistent": False,
        "unit_schema_prerequisites_met": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "local_ledger_mutations": False,
        "broker_order_mutations": False,
        "opening_checkpoint_verified": False,
        "independent_release_review_required": True,
    }
    root = Path(data_dir)
    path = root / "fire-equity-risk.sqlite"
    if (not root.is_dir() or root.is_symlink() or
            not path.is_file() or path.is_symlink()):
        return report
    try:
        with closing(sqlite3.connect(
                path.absolute().as_uri() + "?mode=ro",
                uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                report["reason"] = "ledger_integrity_unverified"
                return report
            report["ledger_integrity_verified"] = True

            tables = {name for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES <= tables:
                report["reason"] = "receipt_schema_migration_required"
                return report
            receipt_cols = {name for _, name, *_ in db.execute(
                "PRAGMA table_info(equity_read_receipts)")}
            if not {"observed_us", "receipt"} <= receipt_cols:
                report["reason"] = "receipt_schema_migration_required"
                return report
            report["receipt_schema_present"] = True

            triggers = {name for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
            if not IMMUTABLE_TRIGGERS <= triggers:
                report["reason"] = "immutable_evidence_triggers_missing"
                return report
            report["immutable_triggers_present"] = True
            try:
                validated_watermark(db)
            except (EquityRiskError, ValueError, TypeError):
                report["reason"] = "historical_watermark_unverified"
                return report
            report["preserved_watermark_consistent"] = True
            db.rollback()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        report["reason"] = "ledger_integrity_unverified"
        return report

    report["reason"] = "none"
    report["status"] = "schema_prerequisites_met_not_release_authority"
    report["unit_schema_prerequisites_met"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args(argv)
    report = inspect_collector_schema(args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["unit_schema_prerequisites_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
