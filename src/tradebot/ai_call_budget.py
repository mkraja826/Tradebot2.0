"""Durable admission quota for paid AI requests, independent of broker safety.

A reservation is permanently charged before inference. A crash, timeout or
restart must never cause another automatically billable request using the same
id. This is a request cap, NOT an accurate dollar-billing ledger.
"""
from contextlib import closing
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import sqlite3

NEW_YORK = ZoneInfo("America/New_York")


class AICallQuota:
    def __init__(self, path, *, daily_limit=8, monthly_limit=160):
        if (type(daily_limit) is not int or type(monthly_limit) is not int
                or not 1 <= daily_limit <= monthly_limit <= 10000):
            raise ValueError("Invalid AI call quota")
        self.path = Path(path)
        self.daily_limit, self.monthly_limit = daily_limit, monthly_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("AI quota ledger must not be a symlink")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os,"O_NOFOLLOW",0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS ai_call_reservations("
                "id TEXT PRIMARY KEY, model TEXT NOT NULL, "
                "local_date TEXT NOT NULL, local_month TEXT NOT NULL, "
                "created_at TEXT NOT NULL)")
            db.commit()

    def claim(self, model, when, call_id):
        if (not isinstance(model,str) or not model
                or not isinstance(call_id,str) or not call_id
                or when.tzinfo is None or when.utcoffset() is None):
            raise ValueError("Expected model, ID and timezone-aware timestamp")
        stamp = when.astimezone(timezone.utc)
        day = when.astimezone(NEW_YORK).date().isoformat()
        month = day[:7]
        with closing(sqlite3.connect(self.path,timeout=20)) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM ai_call_reservations WHERE id=?",
                          (call_id,)).fetchone():
                return False
            day_count = db.execute(
                "SELECT count(*) FROM ai_call_reservations WHERE model=? AND local_date=?",
                (model,day)).fetchone()[0]
            month_count = db.execute(
                "SELECT count(*) FROM ai_call_reservations WHERE model=? AND local_month=?",
                (model,month)).fetchone()[0]
            if day_count >= self.daily_limit or month_count >= self.monthly_limit:
                return False
            db.execute("INSERT INTO ai_call_reservations VALUES (?,?,?,?,?)",
                       (call_id,model,day,month,stamp.isoformat()))
            db.commit()
            return True
