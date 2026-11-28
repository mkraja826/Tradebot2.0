"""Development journal. Use an executor-owned private SQLite database."""
import sqlite3
import re

def initialize_journal(db):
    db.execute("CREATE TABLE IF NOT EXISTS executions (request_id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, target TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed','unknown')), started INTEGER NOT NULL, finished INTEGER)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS execution_target_lock ON executions(target) WHERE status IN ('reserved','unknown')")
    db.commit()

def reserve(db, request_id, digest, target, now):
    if not re.fullmatch("[0-9a-f]{32}",request_id) or not re.fullmatch("[0-9a-f]{64}",digest) or not target or type(now) is not int:
        raise ValueError("invalid reservation")
    try:
        with db:
            db.execute("INSERT INTO executions VALUES (?,?,?,'reserved',?,NULL)",(request_id,digest,target,now))
    except sqlite3.IntegrityError as exc:
        raise ValueError("duplicate request or target locked") from exc

def finish(db, request_id, status, now):
    if status not in ("succeeded","failed","unknown") or type(now) is not int:
        raise ValueError("invalid outcome")
    with db:
        changed=db.execute("UPDATE executions SET status=?,finished=? WHERE request_id=? AND status='reserved' AND started<=?",(status,now,request_id,now)).rowcount
        if changed!=1:
            raise ValueError("reservation unavailable")

def recover_interrupted(db, now):
    """Only after exclusive executor ownership and confirmed absence of active workers."""
    if type(now) is not int:
        raise ValueError("invalid recovery time")
    with db:
        return db.execute("UPDATE executions SET status='unknown',finished=? WHERE status='reserved' AND started<=?",(now,now)).rowcount
