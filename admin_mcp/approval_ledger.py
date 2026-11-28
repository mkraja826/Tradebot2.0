"""Offline prototype. Database must reside in executor-owned private storage."""
import sqlite3

def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS consumed (nonce TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, consumed_at INTEGER NOT NULL)")
    db.commit()

def consume(db, verified_claims, now):
    """Accept only claims returned by independent verification; commit before action."""
    if not verified_claims["issued"] <= now < verified_claims["expires"]:
        raise ValueError("approval expired")
    try:
        with db:
            db.execute("INSERT INTO consumed VALUES (?, ?, ?)", (verified_claims["nonce"], verified_claims["digest"], now))
    except sqlite3.IntegrityError as exc:
        raise ValueError("approval or request already consumed") from exc
