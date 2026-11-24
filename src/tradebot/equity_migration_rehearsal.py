"""Offline-only additive equity-ledger migration rehearsal on a backup copy.

Source is a private pre-existing SQLite online backup in
~/tradebot-backups/full-*/fire-equity-risk.sqlite. The active VM data directory
must never be passed or opened for writing. No broker calls, order permission,
live service changes, forged historical receipts, or trading authorization.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from tradebot.equity_install_preflight import inspect_collector_schema
from tradebot.equity_policy_core import PortfolioEquityGuard


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(conn):
    if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise ValueError("snapshot_integrity_unverified")
    tables = {name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if not {"equity_evidence", "equity_watermark"} <= tables:
        raise ValueError("historical_schema_unavailable")
    observations = conn.execute(
        "SELECT observed_us,equity_usd,origin FROM equity_evidence "
        "ORDER BY observed_us"
    ).fetchall()
    watermark = conn.execute(
        "SELECT singleton,high_usd FROM equity_watermark ORDER BY singleton"
    ).fetchall()
    if not observations or len(watermark) != 1:
        raise ValueError("historical_equity_or_peak_missing")
    receipts = (conn.execute(
        "SELECT observed_us,receipt FROM equity_read_receipts ORDER BY observed_us"
    ).fetchall() if "equity_read_receipts" in tables else [])
    return observations, watermark, receipts


def rehearse_backup_migration(snapshot_dir, *, backup_root=None):
    """Migration writes occur only in freshly created private drill directory."""
    report = {
        "mode": "isolated_backup_copy_migration_rehearsal",
        "status": "blocked",
        "reason": "trusted_backup_unavailable",
        "backup_unmodified": False,
        "historical_observations_preserved": False,
        "peak_watermark_preserved": False,
        "historical_receipts_preserved": False,
        "fabricated_receipts": False,
        "migrated_copy_schema_ready": False,
        "active_service_mutations": False,
        "active_database_mutations": False,
        "broker_order_mutations": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "independent_review_required": True,
        "drill_location": None,
    }
    root = Path(backup_root) if backup_root else Path.home() / "tradebot-backups"
    snap_dir = Path(snapshot_dir)
    original = snap_dir / "fire-equity-risk.sqlite"
    if (not root.is_dir() or root.is_symlink()
            or not snap_dir.is_dir() or snap_dir.is_symlink()
            or not snap_dir.name.startswith("full-")
            or snap_dir.parent.resolve() != root.resolve()
            or not original.is_file() or original.is_symlink()):
        return report
    try:
        input_sha = _sha256(original)
        with closing(sqlite3.connect(
            original.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
        )) as source:
            source.execute("PRAGMA query_only=ON")
            source.execute("BEGIN")
            before = _snapshot(source)
            # Only a normal immutable source backup is accepted here.
            # A new private directory holds the entire rehearsal output.
            os.umask(0o077)
            output = Path(tempfile.mkdtemp(prefix="migration-drill-", dir=root))
            output.chmod(0o700)
            result_path = output / "fire-equity-risk.sqlite"
            with closing(sqlite3.connect(result_path)) as destination:
                source.backup(destination)
            result_path.chmod(0o600)
            source.rollback()
        report["drill_location"] = str(output)
        if _sha256(original) != input_sha:
            report["reason"] = "input_backup_modified"
            return report
        report["backup_unmodified"] = True

        # This is the existing production additive migration logic, but
        # invoked with require_existing=True against ONLY a throwaway copy.
        PortfolioEquityGuard(result_path, require_existing=True)
        with closing(sqlite3.connect(
            result_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
        )) as migrated:
            migrated.execute("PRAGMA query_only=ON")
            migrated.execute("BEGIN")
            after = _snapshot(migrated)
            migrated.rollback()

        report["historical_observations_preserved"] = before[0] == after[0]
        report["peak_watermark_preserved"] = before[1] == after[1]
        report["historical_receipts_preserved"] = before[2] == after[2]
        # No legacy history receipt may be synthesized; a new receipts
        # table is allowed but must have exactly the prior receipt rows.
        report["fabricated_receipts"] = before[2] != after[2]
        check = inspect_collector_schema(output)
        report["migrated_copy_schema_ready"] = (
            check["unit_schema_prerequisites_met"] is True
        )
        report["backup_unmodified"] = _sha256(original) == input_sha
        if all((report["backup_unmodified"],
                report["historical_observations_preserved"],
                report["peak_watermark_preserved"],
                report["historical_receipts_preserved"],
                report["migrated_copy_schema_ready"])):
            report["status"] = "copy_migration_rehearsal_passed_not_release_authority"
            report["reason"] = "none"
        else:
            report["reason"] = "copy_history_or_schema_validation_failed"
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        report["reason"] = "copy_migration_unverified"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", required=True)
    args = parser.parse_args(argv)
    result = rehearse_backup_migration(args.snapshot_dir)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == (
        "copy_migration_rehearsal_passed_not_release_authority") else 2


if __name__ == "__main__":
    raise SystemExit(main())
