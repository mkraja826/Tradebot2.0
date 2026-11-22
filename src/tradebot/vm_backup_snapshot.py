"""Private, WAL-aware SQLite VM snapshots; never deployment or trading authority.

Default CLI is a NO-WRITE preflight. Only explicit --create-backup writes
new files to a separately prepared private backup directory. Uses SQLite's
online backup API: never cp a live database or its potentially active WAL.

Each database snapshot is transactionally consistent on its own. Separate
database backups and append-only journals are NOT cross-file atomic.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_broker_inventory import observe_broker_inventory

MANDATORY = frozenset({
    "fire-ops.sqlite", "fire-xaut.sqlite", "fire-reconciliation.sqlite",
    "fire-equity-risk.sqlite", "fire-monitoring.sqlite",
    "delta-demo-candles.sqlite",
})
MAX_FILES = 48
MAX_BYTES_PER_FILE = 2 * 1024 * 1024 * 1024
MAX_JOURNAL_BYTES = 512 * 1024 * 1024
MAX_BACKUP_SECONDS = 180
SAFE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")


class SnapshotBlocked(ValueError):
    """Sanitized reason; no paths, private account values or SQL rows."""


def _verified_private_regular(path):
    try:
        info = path.lstat()
    except OSError:
        raise SnapshotBlocked("required_private_source_unavailable") from None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o077):
        raise SnapshotBlocked("untrusted_or_permissive_source_file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _verified_private_directory(path):
    try:
        info = path.lstat()
    except OSError:
        raise SnapshotBlocked("private_directory_unavailable") from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise SnapshotBlocked("untrusted_or_permissive_directory")


def _sources(data_dir, backup_root):
    root = Path(data_dir).absolute()
    output = Path(backup_root).absolute()
    _verified_private_directory(root)
    _verified_private_directory(output)
    # The backup must be outside original live data, and the live data must
    # not be under the backup directory, preventing recursive contamination.
    try:
        same = os.path.commonpath((str(root), str(output)))
    except ValueError:
        raise SnapshotBlocked("backup_source_path_untrusted") from None
    if same in (str(root), str(output)):
        raise SnapshotBlocked("backup_source_path_overlap")

    selected = []
    try:
        children = list(root.iterdir())
    except OSError:
        raise SnapshotBlocked("original_data_listing_unavailable") from None
    for p in children:
        if p.name.endswith(".sqlite") or p.name.endswith(".jsonl"):
            if SAFE_NAME.fullmatch(p.name) is None:
                raise SnapshotBlocked("unreviewed_evidence_file_name")
            info = _verified_private_regular(p)
            if info[2] > (MAX_JOURNAL_BYTES if p.suffix == ".jsonl"
                           else MAX_BYTES_PER_FILE):
                raise SnapshotBlocked("evidence_file_above_bounded_backup_size")
            selected.append((p, info))
    if (len(selected) > MAX_FILES
            or not MANDATORY.issubset({p.name for p, _ in selected})):
        raise SnapshotBlocked("required_private_databases_missing_or_unbounded")
    # WAL/SHM are never copied raw. Reject a linked sidecar before SQLite
    # opens the original, preventing a malicious filesystem redirection.
    for path, _ in selected:
        if path.suffix != ".sqlite":
            continue
        for suffix in ("-wal", "-shm", "-journal"):
            linked = Path(str(path) + suffix)
            if linked.is_symlink():
                raise SnapshotBlocked("linked_sqlite_sidecar_untrusted")
    selected.sort(key=lambda entry: entry[0].name)
    return root, output, selected


def _digest(file):
    h = hashlib.sha256()
    with file.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sync(file):
    with file.open("rb") as stream:
        os.fsync(stream.fileno())


def _backup_database(source, dest):
    began = time.monotonic()
    original = _verified_private_regular(source)
    if not original[2]:
        raise SnapshotBlocked("empty_source_database")
    try:
        with closing(sqlite3.connect(
                source.as_uri() + "?mode=ro", uri=True, timeout=5)) as src:
            src.execute("PRAGMA query_only=ON")
            if src.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise SnapshotBlocked("source_sqlite_integrity_failed")
            with closing(sqlite3.connect(str(dest), timeout=5)) as dst:
                def progress(status, remaining, total):
                    if time.monotonic() - began > MAX_BACKUP_SECONDS:
                        raise SnapshotBlocked("sqlite_backup_deadline_exceeded")
                src.backup(dst, pages=256, sleep=0.02, progress=progress)
        # The SQLite online API faithfully copies the source's WAL journal
        # setting. Normalize ONLY the new destination to DELETE mode, which
        # checkpoints its own copied pages and removes destination -wal/-shm.
        # Never run journal_mode or checkpoint on the original live source.
        with closing(sqlite3.connect(str(dest), timeout=5)) as standalone:
            chosen = standalone.execute("PRAGMA journal_mode=DELETE").fetchone()
            if chosen != ("delete",):
                raise SnapshotBlocked("backup_cannot_be_made_standalone")
        if any(Path(str(dest) + suffix).exists()
               for suffix in ("-wal", "-shm", "-journal")):
            raise SnapshotBlocked("backup_has_uncheckpointed_destination_sidecars")
        if _verified_private_regular(source)[:2] != original[:2]:
            raise SnapshotBlocked("source_database_replaced_during_backup")
        with closing(sqlite3.connect(
                dest.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)) as check:
            check.execute("PRAGMA query_only=ON")
            if check.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise SnapshotBlocked("backup_integrity_failed")
            if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise SnapshotBlocked("backup_foreign_key_integrity_failed")
    except (sqlite3.Error, OSError, TimeoutError):
        raise SnapshotBlocked("sqlite_online_backup_unavailable") from None
    os.chmod(dest, 0o600)
    _sync(dest)


def _backup_log(source, dest):
    original = _verified_private_regular(source)
    try:
        with source.open("rb") as inp, dest.open("xb") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if _verified_private_regular(source) != original:
            raise SnapshotBlocked("append_only_journal_changed_during_backup")
    except OSError:
        raise SnapshotBlocked("append_only_journal_backup_unavailable") from None
    os.chmod(dest, 0o600)


def _flatness_verified(result):
    return (type(result) is dict
            and result.get("observation_status")
            == "two_flat_snapshots_observed_not_trade_authority"
            and result.get("samples_checked") == 2
            and result.get("sample_interval_verified") is True
            and result.get("broker_positions_last") == 0
            and result.get("broker_open_orders_last") == 0
            and result.get("blockers") == []
            and result.get("trade_authorized") is False
            and result.get("order_mutations") is False
            and result.get("safe_to_enable_fire") is False)


def run_snapshot(data_dir, backup_root, *, create=False, require_broker_flat=False,
                 exchange=None, inventory_check=observe_broker_inventory):
    """Validate sources first; optionally take private, integrity-tested backup.

    A snapshot succeeds even if broker proof is not requested. But it can
    never authorize a deployment; broker proof must be fresh at the actual
    protected cutover, independently from this earlier snapshot.
    """
    report = {
        "status": "blocked", "reason": "not_checked",
        "preflight_sources_verified": False,
        "backup_completed": False, "backup_file_count": 0,
        "snapshot_path": None,
        "signed_two_sweep_flatness_observed": False,
        "cross_database_atomic": False,
        "original_data_mutations": False, "service_mutations": False,
        "broker_order_mutations": False, "ai_calls": 0,
        "trade_authorized": False, "safe_to_deploy": False,
        "safe_to_enable_fire": False,
    }
    try:
        root, output, selected = _sources(data_dir, backup_root)
        report["preflight_sources_verified"] = True
        if require_broker_flat:
            if (getattr(exchange, "base_url", None) != DEMO_API
                    or getattr(exchange, "allow_orders", None) is not False):
                raise SnapshotBlocked("read_only_demo_broker_required")
            try:
                evidence = inventory_check(exchange, root)
            except Exception:
                raise SnapshotBlocked("authenticated_account_flatness_unavailable") from None
            if not _flatness_verified(evidence):
                raise SnapshotBlocked("two_signed_flat_broker_sweeps_unverified")
            report["signed_two_sweep_flatness_observed"] = True
        if not create:
            report["status"] = "source_preflight_only"
            report["reason"] = "backup_not_requested"
            return report

        # Only after ALL preconditions pass may a new, uniquely named
        # directory be allocated. Never modify/delete the source databases.
        staged = Path(tempfile.mkdtemp(prefix=".incomplete-snapshot-", dir=output))
        try:
            os.chmod(staged, 0o700)
            entries = []
            for source, _ in selected:
                target = staged / source.name
                if source.suffix == ".sqlite":
                    _backup_database(source, target)
                else:
                    _backup_log(source, target)
                entries.append({
                    "file": source.name, "bytes": target.stat().st_size,
                    "sha256": _digest(target),
                })
            manifest = {
                "version": 1,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "format": "individual_sqlite_online_backup_with_wal",
                "individual_database_integrity_verified": True,
                "cross_database_atomic": False,
                "deployment_authorized": False,
                "broker_order_mutations": False,
                "files": entries,
            }
            out = staged / "manifest.json"
            with out.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(out, 0o600)
            # Make each newly created file durable before renaming stage.
            dirfd = os.open(str(staged), os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
            final = output / ("snapshot-" + staged.name.split(
                ".incomplete-snapshot-", 1)[-1])
            # Randomized unique destination generated by tempfile; fail
            # rather than replace any pre-existing snapshot.
            if final.exists() or final.is_symlink():
                raise SnapshotBlocked("backup_destination_already_exists")
            staged.rename(final)
            fd = os.open(str(output), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            report["status"] = "backup_integrity_verified"
            report["reason"] = "independent_deployment_review_required"
            report["backup_completed"] = True
            report["backup_file_count"] = len(entries)
            report["snapshot_path"] = str(final)
        except Exception:
            # Keep the new, private incomplete snapshot for forensic recovery.
            # Never mistake it for a completed snapshot with manifest.
            raise SnapshotBlocked("incomplete_private_backup_requires_review") from None
    except SnapshotBlocked as error:
        report["status"] = "blocked"
        report["reason"] = str(error)
    except (OSError, ValueError, TypeError):
        report["status"] = "blocked"
        report["reason"] = "vm_backup_preflight_unavailable"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--create-backup", action="store_true")
    parser.add_argument("--require-two-signed-flat-sweeps", action="store_true")
    args = parser.parse_args(argv)
    exchange = None
    if args.require_two_signed_flat_sweeps:
        exchange = DeltaDemo(allow_orders=False)
    report = run_snapshot(args.data_dir, args.backup_root,
                          create=args.create_backup,
                          require_broker_flat=args.require_two_signed_flat_sweeps,
                          exchange=exchange)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    print("TRADING_ENABLED: false")
    # Snapshot success is not VM deployment readiness. Shell exit 0 means
    # only a local backup/check completed, not independent release signoff.
    return 0 if report["status"] in (
        "source_preflight_only", "backup_integrity_verified") else 2


if __name__ == "__main__":
    raise SystemExit(main())
