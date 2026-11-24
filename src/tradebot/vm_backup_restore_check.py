"""Offline verification and isolated restore rehearsal of private VM snapshots.

Never connect to a broker, import/execute trade machinery, write original
data/backup, run systemd, or claim deployment/trading authority.
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
import sys
import tempfile

from tradebot.vm_backup_snapshot import (
    MANDATORY, MAX_FILES, MAX_BYTES_PER_FILE, MAX_JOURNAL_BYTES,
    SAFE_NAME, SnapshotBlocked, _verified_private_directory,
    _verified_private_regular, _digest,
)

HASH = re.compile(r"[0-9a-f]{64}\Z")
SNAPSHOT_NAME = re.compile(r"snapshot-[A-Za-z0-9_-]{8,64}\Z")
MAX_MANIFEST_BYTES = 128 * 1024


def _unique_fields(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise SnapshotBlocked("duplicate_manifest_fields")
        out[key] = value
    return out


def _manifest(snapshot):
    if SNAPSHOT_NAME.fullmatch(snapshot.name) is None:
        raise SnapshotBlocked("completed_snapshot_name_unverified")
    _verified_private_directory(snapshot)
    file = snapshot / "manifest.json"
    _verified_private_regular(file)
    if file.stat().st_size > MAX_MANIFEST_BYTES or file.stat().st_size == 0:
        raise SnapshotBlocked("snapshot_manifest_size_invalid")
    try:
        with file.open("r", encoding="utf-8") as stream:
            doc = json.load(stream, object_pairs_hook=_unique_fields)
    except SnapshotBlocked:
        raise
    except (ValueError, OSError, UnicodeError):
        raise SnapshotBlocked("snapshot_manifest_unreadable") from None
    if type(doc) is not dict or set(doc) != {
            "version", "created_at_utc", "format",
            "individual_database_integrity_verified", "cross_database_atomic",
            "deployment_authorized", "broker_order_mutations", "files"}:
        raise SnapshotBlocked("snapshot_manifest_structure_unverified")
    if (type(doc["version"]) is not int or doc["version"] != 1
            or doc["format"] != "individual_sqlite_online_backup_with_wal"
            or doc["individual_database_integrity_verified"] is not True
            or doc["cross_database_atomic"] is not False
            or doc["deployment_authorized"] is not False
            or doc["broker_order_mutations"] is not False):
        raise SnapshotBlocked("snapshot_manifest_safety_flags_invalid")
    try:
        instant = datetime.fromisoformat(doc["created_at_utc"])
        if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
            raise ValueError("not UTC")
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise SnapshotBlocked("snapshot_manifest_timestamp_unverified") from None
    entries = doc["files"]
    if type(entries) is not list or not len(MANDATORY) <= len(entries) <= MAX_FILES:
        raise SnapshotBlocked("snapshot_manifest_file_count_invalid")
    verified = {}
    for entry in entries:
        if (type(entry) is not dict or set(entry) != {"file", "bytes", "sha256"}
                or type(entry["file"]) is not str
                or SAFE_NAME.fullmatch(entry["file"]) is None
                or not (entry["file"].endswith(".sqlite")
                        or entry["file"].endswith(".jsonl"))
                or type(entry["bytes"]) is not int
                or entry["bytes"] < 0
                or type(entry["sha256"]) is not str
                or HASH.fullmatch(entry["sha256"]) is None):
            raise SnapshotBlocked("snapshot_manifest_entry_invalid")
        name = entry["file"]
        max_size = (MAX_BYTES_PER_FILE if name.endswith(".sqlite")
                    else MAX_JOURNAL_BYTES)
        if (entry["bytes"] > max_size
                or (name.endswith(".sqlite") and entry["bytes"] == 0)
                or name in verified):
            raise SnapshotBlocked("snapshot_manifest_duplicate_or_oversized_entry")
        verified[name] = entry
    if not MANDATORY.issubset(verified):
        raise SnapshotBlocked("snapshot_missing_critical_evidence")

    # Complete inventory: no undeclared files, extra DBs, symlinks, copied
    # WAL/SHM, private credentials, staging files or subdirectories.
    try:
        observed = {part.name for part in snapshot.iterdir()}
    except OSError:
        raise SnapshotBlocked("snapshot_inventory_unreadable") from None
    if observed != (set(verified) | {"manifest.json"}):
        raise SnapshotBlocked("snapshot_contains_unaccounted_files")
    return verified


def _check_database(path):
    try:
        with closing(sqlite3.connect(
                path.absolute().as_uri() + "?mode=ro&immutable=1",
                uri=True, timeout=5)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise SnapshotBlocked("restored_database_integrity_failed")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise SnapshotBlocked("restored_foreign_key_integrity_failed")
            mode = conn.execute("PRAGMA journal_mode").fetchone()
            if mode != ("delete",):
                raise SnapshotBlocked("standalone_sqlite_journal_unverified")
            # Only retain a digest of schema, never schema text or user data.
            rows = conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "ORDER BY type,name,tbl_name").fetchall()
            if not rows:
                raise SnapshotBlocked("restored_database_schema_missing")
            return hashlib.sha256(
                json.dumps(rows, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
    except SnapshotBlocked:
        raise
    except (sqlite3.Error, UnicodeError, OSError, ValueError):
        raise SnapshotBlocked("restored_database_unreadable") from None


def _private_copy(source, dest):
    # Exclusive 0600 create; never write existing destination or follow
    # a destination symlink. Source inode and hash are checked again later.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(dest, flags, 0o600)
        with os.fdopen(fd, "wb") as output, source.open("rb") as original:
            shutil.copyfileobj(original, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        raise SnapshotBlocked("isolated_restore_copy_failed") from None


def verify_snapshot(snapshot_dir, *, rehearsal_root=None):
    """Read-only verification by default; optional isolated ephemeral restore."""
    result = {
        "status": "blocked", "reason": "not_checked",
        "manifest_verified": False, "checksums_verified": False,
        "standalone_sqlite_integrity_verified": False,
        "isolated_restore_exercised": False,
        "files_verified": 0,
        "cross_database_atomic": False,
        "source_files_modified": False, "broker_requests": 0,
        "service_mutations": False, "trade_authorized": False,
        "safe_to_deploy": False, "safe_to_enable_fire": False,
    }
    try:
        snapshot = Path(snapshot_dir).absolute()
        # Never resolve symlinks; lstat validates original object identity.
        entries = _manifest(snapshot)
        result["manifest_verified"] = True
        known = {}
        for name, entry in sorted(entries.items()):
            path = snapshot / name
            identity = _verified_private_regular(path)
            if identity[2] != entry["bytes"] or _digest(path) != entry["sha256"]:
                raise SnapshotBlocked("snapshot_file_checksum_mismatch")
            if _verified_private_regular(path) != identity:
                raise SnapshotBlocked("snapshot_file_changed_during_hash")
            known[name] = (identity, entry["sha256"])
        result["checksums_verified"] = True

        original_schemas = {}
        for name in sorted(known):
            if not name.endswith(".sqlite"):
                continue
            path = snapshot / name
            original_schemas[name] = _check_database(path)
            if (_verified_private_regular(path) != known[name][0]
                    or _digest(path) != known[name][1]):
                raise SnapshotBlocked("snapshot_database_changed_during_integrity")
        result["standalone_sqlite_integrity_verified"] = True
        result["files_verified"] = len(known)

        if rehearsal_root is not None:
            rehearsal = Path(rehearsal_root).absolute()
            _verified_private_directory(rehearsal)
            try:
                common = os.path.commonpath((str(snapshot), str(rehearsal)))
            except ValueError:
                raise SnapshotBlocked("restore_destination_untrusted") from None
            if common in (str(snapshot), str(rehearsal)):
                raise SnapshotBlocked("restore_destination_overlaps_snapshot")
            # TemporaryDirectory creates a private 0700 destination and
            # deletes only its own newly-created contents. No changes to
            # the original snapshot or running VM data.
            try:
                with tempfile.TemporaryDirectory(
                        prefix="isolated-restore-", dir=rehearsal) as fresh:
                    target_dir = Path(fresh)
                    for name, (identity, digest) in sorted(known.items()):
                        source = snapshot / name
                        restored = target_dir / name
                        _private_copy(source, restored)
                        if (_verified_private_regular(source) != identity
                                or _digest(source) != digest
                                or _digest(restored) != digest):
                            raise SnapshotBlocked("isolated_restore_file_mismatch")
                        if name.endswith(".sqlite"):
                            if _check_database(restored) != original_schemas[name]:
                                raise SnapshotBlocked("isolated_restore_schema_mismatch")
                    result["isolated_restore_exercised"] = True
            except SnapshotBlocked:
                raise
            except (OSError, ValueError):
                raise SnapshotBlocked("isolated_restore_unavailable") from None
        result["status"] = "backup_independently_verified"
        result["reason"] = ("rehearsal_completed_not_deployment_authority"
                            if rehearsal_root is not None
                            else "read_only_backup_verification_only")
    except SnapshotBlocked as error:
        result["reason"] = str(error)
    except (OSError, ValueError, TypeError):
        result["reason"] = "snapshot_verification_unavailable"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--restore-rehearsal-root",
                        help="existing private directory, separate from snapshot")
    args = parser.parse_args(argv)
    result = verify_snapshot(
        args.snapshot, rehearsal_root=args.restore_rehearsal_root)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    print("TRADING_ENABLED: false")
    return 0 if result["status"] == "backup_independently_verified" else 2


if __name__ == "__main__":
    sys.exit(main())
