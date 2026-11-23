"""One-time audited owner review of a historical NO-ORDER BTC model failure.

Never modifies trade receipts, removes the halt latch, arms the worker, sends an
exchange mutation or requests an AI completion. Future attempts still require
fresh signed DEMO broker preflight and the separate owner-controlled arm file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

MARKER_NAME = "btc-auto-reviewed-no-order.json"
APPROVAL = "REVIEW BTC DEMO MODEL FAILURE WITH NO ORDER"
MAX_MARKER_BYTES = 400


def evidence(root):
    """Identify the exact latest model failure, proven no-order in the ledger."""
    root = Path(root)
    path = root / "fire-ops.sqlite"
    if root.is_symlink() or not root.is_dir() or path.is_symlink() or not path.is_file():
        return None
    try:
        with sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT press, status, result FROM fire_requests "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
            if not row:
                return None
            press, status, result = row
            if (not isinstance(press, str) or not re.fullmatch("[0-9a-f]{32}", press)
                    or status != "rejected_no_order" or not isinstance(result, str)):
                return None
            receipt = json.loads(result)
            if (type(receipt) is not dict
                    or receipt.get("reason_code") != "model_decision_failed"
                    or receipt.get("orders_submitted") is not False
                    or receipt.get("protection_verified") is True):
                return None
            # An unresolved intent is never released by a model-error review.
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='fire_entries'").fetchone()
            if not exists or db.execute(
                    "SELECT 1 FROM fire_entries WHERE press=? LIMIT 1", (press,)
            ).fetchone():
                return None
            digest = hashlib.sha256(
                (press + "\x00" + status + "\x00" + result).encode("utf-8")
            ).hexdigest()
            return {"press": press, "receipt_sha256": digest,
                    "reason_code": "model_decision_failed"}
    except (OSError, sqlite3.Error, ValueError, TypeError, UnicodeError):
        return None


def _receipt_scoped_marker(root, required):
    """Write-once marker avoids overwriting an earlier operator review."""
    return root / ("btc-auto-reviewed-no-order-" + required["press"] + ".json")


def _marker_matches(path, required):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1 or info.st_size > MAX_MARKER_BYTES):
                return False
            payload = os.read(fd, MAX_MARKER_BYTES + 1)
        finally:
            os.close(fd)
        obj = json.loads(payload)
        return type(obj) is dict and obj == required
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def reviewed_receipt_matches(root):
    """Require an exact private 0600 acknowledgment for the latest receipt.

    The original legacy marker stays valid for its own immutable receipt.
    Later receipts get independent write-once markers, preserving audit history.
    """
    root = Path(root)
    required = evidence(root)
    if required is None:
        return False
    return any(_marker_matches(path, required) for path in (
        root / MARKER_NAME, _receipt_scoped_marker(root, required)))


def _signed_candidate(root):
    from tradebot.btc_autonomous_demo import check_candidate
    return check_candidate(root)


def acknowledge(root, *, approval, candidate=_signed_candidate):
    """Explicit owner-reviewed local no-order acknowledgement, no API mutation."""
    root = Path(root)
    if approval != APPROVAL or root.is_symlink() or not root.is_dir():
        raise ValueError("Explicit review consent and trusted data directory required")
    before = evidence(root)
    if before is None:
        raise ValueError("No exact locally verified model-failure no-order receipt")
    if reviewed_receipt_matches(root):
        return {"status": "already_reviewed", "broker_mutations": False,
                "ai_calls": 0}
    # Signed authenticated account-wide flatness, equity and independent
    # protective services must pass immediately before accepting the review.
    if candidate(root) is not True:
        raise ValueError("Fresh signed DEMO broker preflight is not verified")
    after = evidence(root)
    if after is None or after != before:
        raise ValueError("Prior receipt changed during broker preflight")
    # Preserve the original review record unchanged: it might belong to a
    # different historical no-order attempt. The latest review is write-once
    # and bound to the exact latest immutable FIRE receipt and consent.
    legacy = root / MARKER_NAME
    marker = (legacy if not legacy.exists() and not legacy.is_symlink()
              else _receipt_scoped_marker(root, before))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(marker, flags, 0o600)
    try:
        os.write(fd, (json.dumps(after, sort_keys=True, separators=(",", ":")) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if not reviewed_receipt_matches(root):
        raise ValueError("Review marker could not be verified")
    return {"status": "reviewed_no_order", "broker_mutations": False,
            "ai_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--acknowledge", action="store_true")
    parser.add_argument("--approval", default="")
    args = parser.parse_args(argv)
    if not args.acknowledge:
        print(json.dumps({
            "status": "already_reviewed" if reviewed_receipt_matches(args.data_dir)
            else ("awaiting_no_order_review" if evidence(args.data_dir)
                  else "not_eligible_for_review"),
            "order_authorized": False, "ai_calls": 0}))
        return 0
    try:
        report = acknowledge(args.data_dir, approval=args.approval)
    except (ValueError, OSError):
        report = {"status": "review_blocked", "broker_mutations": False, "ai_calls": 0}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in ("reviewed_no_order", "already_reviewed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
