"""Local provisioning CLI. Run as root from a trusted terminal only.
Policy and database paths must be supplied by the deployment administrator.
"""
import argparse
import json
import os
import pwd
import sqlite3
import stat
import sys
from contextlib import closing
from pathlib import Path
from provisioning_session import initialize, issue
from enrollment_session_binding import initialize as initialize_binding

def main():
    if os.geteuid() != 0 or not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("Root and interactive terminal required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    policy_path = Path(args.policy)
    db_path = Path(args.database)
    for path in (policy_path, db_path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise SystemExit("Private regular files required")
    if policy_path.stat().st_uid != 0:
        raise SystemExit("Root-owned policy required")
    policy = json.loads(policy_path.read_text())
    if policy.get("origin") != "https://tradingbot.micirql.com" or policy.get("rp_id") != "tradingbot.micirql.com":
        raise SystemExit("Invalid host policy")
    account = pwd.getpwnam("recover-approval")
    if account.pw_uid == 0 or db_path.stat().st_uid != account.pw_uid:
        raise SystemExit("Database must belong to the approval service account")
    db_path = db_path.resolve(strict=True)
    os.umask(0o077)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    if os.geteuid() == 0:
        raise SystemExit("Privilege drop failed")
    with closing(sqlite3.connect(db_path.resolve().as_uri()+"?mode=rw", uri=True)) as db:
        initialize(db)
        initialize_binding(db)
        token = issue(db, args.principal, policy, args.operator)
    print("Private enrollment token (expires in five minutes):")
    print(token)

if __name__ == "__main__":
    main()
