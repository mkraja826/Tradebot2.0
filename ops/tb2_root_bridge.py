#!/usr/bin/python3
"""Locally installed, root-owned execution bridge for a PRIVATE ChatGPT MCP tunnel.

This intentionally grants arbitrary ROOT execution to the approved tunnel OS
identity. The owner must opt in locally. A compromised tunnel/ChatGPT account
could fully compromise the VM; never expose this through the web dashboard.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
from datetime import datetime, timezone

ENABLE_PATH = "/etc/tradebot2/root-bridge.enabled"
AUDIT_PATH = "/var/log/tradebot2-root-admin.log"
OUT_LIMIT = 8000
# Best-effort output masking; does not guarantee arbitrary shell output is
# secret-free. Privileged operator must not request secret material.
SENSITIVE = re.compile(
    r"(?i)(api[ _-]?(?:key|secret)|password|private[ _-]?key|"
    r"auth(?:orization)?[ _-]?token|credential|bearer|token|secret)"
)


def _report(status, command_hash, *, code=None, output="", truncated=False):
    print(json.dumps({
        "status": status,
        "command_sha256": command_hash,
        "exit_code": code,
        "output": output,
        "truncated": truncated,
    }, separators=(",", ":"), sort_keys=True), flush=True)


def _is_root_private_file(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and (info.st_mode & 0o077) == 0
            and info.st_nlink == 1)


def _audit(command_hash, event):
    # Append-only best-effort at the application level, root-owned 0600 and
    # O_NOFOLLOW to prevent a symlink redirection. FAIL CLOSED on log error.
    os.makedirs("/var/log", exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(AUDIT_PATH, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o077):
            raise PermissionError("Privileged audit file permissions invalid")
        record = {
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "sudo_user": os.environ.get("SUDO_USER", "")[:64],
            "command_sha256": command_hash,
            "event": event,
        }
        os.write(fd, (json.dumps(record, separators=(",", ":")) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def _clean_output(raw):
    lines = raw.decode("utf-8", errors="replace").splitlines()
    filtered = [
        "[redacted potentially sensitive output]"
        if SENSITIVE.search(line) else line
        for line in lines
    ]
    joined = "\n".join(filtered)
    return joined[:OUT_LIMIT], len(joined) > OUT_LIMIT


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("command")
    args = parser.parse_args(argv)
    if (not 1 <= args.timeout <= 30
            or not args.command.strip()
            or len(args.command) > 4096
            or "\x00" in args.command):
        parser.error("Invalid root bridge invocation")

    command_hash = hashlib.sha256(args.command.encode()).hexdigest()
    # Never report command contents or the user name through MCP.
    if (os.geteuid() != 0 or not os.environ.get("SUDO_USER")
            or not _is_root_private_file(ENABLE_PATH)):
        _report("disabled", command_hash)
        return 3
    try:
        _audit(command_hash, "requested")
    except OSError:
        _report("rejected", command_hash)
        return 3

    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": "/root",
        "USER": "root",
    }
    process = None
    timed_out = False
    try:
        process = subprocess.Popen(
            ["/bin/bash", "-o", "pipefail", "-c", args.command],
            cwd="/", env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            raw, _ = process.communicate(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            raw, _ = process.communicate(timeout=3)
        output, truncated = _clean_output(raw)
        code = process.returncode
        if type(code) is not int or code < 0 or code > 255:
            code = None
        _audit(command_hash, "timed_out" if timed_out else "completed")
        _report("timed_out" if timed_out else "completed", command_hash,
                code=code, output=output, truncated=truncated)
        return 124 if timed_out else 0
    except (OSError, subprocess.TimeoutExpired):
        try:
            _audit(command_hash, "rejected")
        except OSError:
            pass
        _report("rejected", command_hash)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
