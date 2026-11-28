"""Activate a reserved release from the operator-managed Gold demo release tree."""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from gold_deployment import UNIT

ROOT = Path("/opt/recover-gold-v2-execution")
STATUS = Path("/var/lib/recover-trading/gold-v2-mark-execution/mark_execution_status.json")


def release(revision):
    if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
        raise ValueError("invalid revision")
    path = ROOT / "releases" / revision
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("release unavailable")
    return path


def activate(expected, destination):
    current = ROOT / "current"
    if not current.is_symlink() or current.resolve(strict=True) != expected:
        raise ValueError("installed release changed")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        link = Path(tmp) / "current"
        link.symlink_to(destination)
        os.replace(link, current)


def restart_and_verify(path):
    subprocess.run(["/usr/bin/systemctl", "restart", UNIT], check=True, timeout=210)
    started = time.time()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        pid = subprocess.check_output(["/usr/bin/systemctl", "show", UNIT, "-p", "MainPID", "--value"],
                                      text=True, timeout=5).strip()
        try:
            if pid.isdecimal() and (Path("/proc") / pid / "cwd").resolve(strict=True) == path:
                with STATUS.open() as stream:
                    report = json.loads(stream.read(65537))
                if (report.get("symbol") == "XAUTUSD" and report.get("mode") == "demo_mark_execution"
                        and started <= report["timestamp"] <= time.time()
                        and report.get("controller", {}).get("status") and not report.get("errors")):
                    return
        except (FileNotFoundError, KeyError, ValueError, TypeError):
            pass
        time.sleep(1)
    raise RuntimeError("fresh Gold demo heartbeat unavailable")


def run_reserved(db, request_id):
    if db.in_transaction:
        raise ValueError("exclusive connection required")
    with db:
        row = db.execute("SELECT previous_revision, release_revision FROM gold_deployments WHERE request_id=?",
                         (request_id,)).fetchone()
        if not row or db.execute("UPDATE executions SET status='unknown' WHERE request_id=? AND target=? AND status='reserved'",
                                 (request_id, UNIT)).rowcount != 1:
            raise ValueError("fresh Gold reservation required")
    outcome = "unknown"
    try:
        previous, desired = map(release, row)
        activate(previous, desired)
        try:
            restart_and_verify(desired)
            outcome = "succeeded"
        except Exception:
            activate(desired, previous)
            restart_and_verify(previous)
            outcome = "failed"
    finally:
        with db:
            db.execute("UPDATE executions SET status=?, finished=? WHERE request_id=? AND status='unknown'",
                       (outcome, int(time.time()), request_id))
    return {"status": outcome, "target": UNIT}
