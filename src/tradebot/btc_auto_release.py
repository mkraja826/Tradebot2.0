"""Audited, DEMO-only release of one proven no-order autonomous halt.

Not a generic reset command. Refuse any unreviewed, broker-exposed,
stale, malformed or ambiguous halt. The worker must be stopped separately.
Never changes the immutable FIRE receipt, account configuration or arming.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess

from tradebot.btc_auto_review import evidence, reviewed_receipt_matches
from tradebot.btc_autonomous_demo import (
    check_candidate, prior_fire_receipts_safe, is_armed,
)

RELEASE_APPROVAL = "RELEASE REVIEWED NO-ORDER BTC DEMO HALT"
MAX_HALT_DRIFT_SECONDS = 10


def worker_stopped():
    """Fail closed when systemd is unavailable or service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet",
             "tradebot2-btc-autonomous-demo.service"],
            timeout=4, check=False, capture_output=True)
        return result.returncode == 3  # specifically inactive, not unknown
    except (OSError, subprocess.TimeoutExpired):
        return False


def _latest_attempt_matches(root, press):
    path = root / "btc-auto-demo.sqlite"
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                             uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT attempt_id,status FROM btc_auto_attempts "
                "ORDER BY requested_at DESC, rowid DESC LIMIT 1").fetchone()
            return row == (press, "rejected_no_order")
    except sqlite3.Error:
        return False


def release_reviewed_no_order_halt(
        root, *, approval, candidate=check_candidate,
        stopped=worker_stopped, armed=is_armed):
    """Release only a halt cryptographically associated with the reviewed no-order.

    Broker preflight and stop condition remain enforced by every future entry.
    """
    root = Path(root)
    if (approval != RELEASE_APPROVAL or root.is_symlink()
            or not root.is_dir() or not stopped()):
        raise ValueError("Explicit release approval, trusted root and stopped worker required")
    required = evidence(root)
    if (required is None or not reviewed_receipt_matches(root)
            or not prior_fire_receipts_safe(root)
            or not _latest_attempt_matches(root, required["press"])):
        raise ValueError("No exact reviewed no-order attempt eligible for release")

    halt = root / "btc-auto-demo-halt"
    try:
        info = halt.lstat()
    except OSError:
        raise ValueError("No halt file to release") from None
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid() or info.st_nlink != 1
            or info.st_size != 0):
        raise ValueError("Invalid or untrusted halt marker")

    with sqlite3.connect((root / "fire-ops.sqlite").absolute().as_uri()
                         + "?mode=ro", uri=True, timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        last = db.execute(
            "SELECT press,status,updated_at FROM fire_requests "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    if (not last or last[0] != required["press"]
            or last[1] != "rejected_no_order"):
        raise ValueError("Reviewed FIRE receipt no longer latest")
    try:
        timestamp = datetime.fromisoformat(last[2])
        if timestamp.tzinfo is None:
            raise ValueError
        delta = abs(info.st_mtime - timestamp.timestamp())
    except (TypeError, ValueError):
        raise ValueError("Invalid receipt time") from None
    if delta > MAX_HALT_DRIFT_SECONDS:
        raise ValueError("Halt is not time-bound to the reviewed no-order incident")

    # The authenticated broker exposure/monitoring preflight is independently
    # checked before writing any release audit. Model response is not authority.
    if armed() is not True or candidate(root) is not True:
        raise ValueError("Fresh signed DEMO preflight or owner arming is invalid")
    if (not stopped() or evidence(root) != required
            or not reviewed_receipt_matches(root)
            or not prior_fire_receipts_safe(root)):
        raise ValueError("Release evidence changed during verification")
    current = halt.lstat()
    if (current.st_dev, current.st_ino, current.st_mtime_ns) != (
            info.st_dev, info.st_ino, info.st_mtime_ns):
        raise ValueError("Halt changed during verification")

    audit = root / ("btc-auto-halt-release-" + required["press"] + ".json")
    audit_data = {
        "press": required["press"],
        "receipt_sha256": required["receipt_sha256"],
        "halt_mtime_ns": info.st_mtime_ns,
        "release_approval": RELEASE_APPROVAL,
        "broker_preflight": "signed_demo_flat_and_watchdog_verified",
        "released_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(audit, flags, 0o600)
    try:
        os.write(fd, (json.dumps(audit_data, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    # Service was stopped, and this exact inode was linked to the reviewed
    # receipt. Remove only its one matching halt; never wildcard-clear history.
    os.unlink(halt)
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"status": "reviewed_no_order_halt_released",
            "press": required["press"], "trade_authorized": False,
            "broker_mutations": False, "ai_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--approval", default="")
    args = parser.parse_args(argv)
    if not args.release:
        print(json.dumps({"status": "release_requires_explicit_approval",
                          "trade_authorized": False}))
        return 0
    try:
        result = release_reviewed_no_order_halt(
            args.data_dir, approval=args.approval)
    except (ValueError, OSError, sqlite3.Error):
        result = {"status": "halt_release_blocked",
                  "trade_authorized": False,
                  "broker_mutations": False, "ai_calls": 0}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "reviewed_no_order_halt_released" else 2


if __name__ == "__main__":
    raise SystemExit(main())
