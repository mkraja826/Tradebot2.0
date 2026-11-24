"""Durable, restart-safe shadow observations for Strategy V2.

No broker/AI API clients, trade hooks or executable dispatch live here.
A matching symbol/candle can be observed only once, even after restarts.
"""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import sqlite3
import stat

from tradebot.signal_ai_router import AI_ROUTE

SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_observations (
 event_id TEXT PRIMARY KEY,
 symbol TEXT NOT NULL,
 candle_time INTEGER NOT NULL,
 model_route TEXT NOT NULL,
 direction_hint TEXT,
 strategy_count INTEGER NOT NULL,
 strongest_score INTEGER NOT NULL,
 conflicting_directions INTEGER NOT NULL,
 evidence_hash TEXT NOT NULL,
 first_seen_utc TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state='observed_only'),
 UNIQUE(symbol,candle_time)
);
"""


class SignalJournal:
    """Fail-closed no-order signal journal; isolated from trade ledgers."""

    def __init__(self, path):
        self.path = Path(path)
        parent = self.path.parent
        if not parent.is_dir() or parent.is_symlink():
            raise ValueError("signal_journal_parent_not_private_directory")
        parent_stat = parent.stat()
        if parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) != 0o700:
            raise ValueError("signal_journal_parent_not_private_directory")
        if self.path.is_symlink():
            raise ValueError("signal_journal_symlink")
        if self.path.exists():
            file_stat = self.path.stat()
            if (not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(file_stat.st_mode) != 0o600):
                raise ValueError("signal_journal_file_not_private")
        else:
            # The journal never writes to the existing broker execution ledgers.
            fd = os.open(self.path, os.O_CREAT|os.O_EXCL|os.O_WRONLY
                         |getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(fd)
        with closing(self._connect()) as db:
            db.executescript(SCHEMA)
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.execute("PRAGMA busy_timeout=3000")
        return db

    def observe(self, event):
        """Return new/duplicate/changed; never dispatch an AI call."""
        if (not isinstance(event, dict)
                or event.get("status") != "ready_for_ai_evaluation"
                or event.get("dispatch_ai") is not True
                or event.get("execution_authorized") is not False
                or event.get("requires_fresh_broker_and_risk_checks") is not True
                or event.get("symbol") not in AI_ROUTE
                or event.get("model") != AI_ROUTE.get(event.get("symbol"))
                or type(event.get("candle_time")) is not int
                or event["candle_time"] % 300
                or type(event.get("event_id")) is not str
                or len(event["event_id"]) != 24):
            raise ValueError("invalid_signal_observation")
        signals = event.get("signals")
        if not isinstance(signals, list) or not 1 <= len(signals) <= 20:
            raise ValueError("invalid_signal_observation")
        # fingerprint only the already validated AI routing contract.
        serialized = json.dumps(event, sort_keys=True, separators=(",", ":"))
        fingerprint = sha256(serialized.encode()).hexdigest()
        highest = max(int(s["score"]) for s in signals)
        record = (
            event["event_id"], event["symbol"], event["candle_time"],
            event["model"], None, len(signals), highest,
            int(event["conflicting_directions"]), fingerprint,
            datetime.now(timezone.utc).isoformat(), "observed_only",
        )
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT OR IGNORE INTO signal_observations(
                event_id,symbol,candle_time,model_route,direction_hint,
                strategy_count,strongest_score,conflicting_directions,
                evidence_hash,first_seen_utc,state)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", record)
            inserted = db.execute("SELECT changes()").fetchone()[0] == 1
            row = db.execute("""SELECT event_id,evidence_hash
                FROM signal_observations WHERE symbol=? AND candle_time=?""",
                (event["symbol"],event["candle_time"])).fetchone()
            db.commit()
        if row is None:
            raise RuntimeError("signal_observation_not_persisted")
        if row[0] != event["event_id"] or row[1] != fingerprint:
            return {"status":"signal_changed_on_completed_candle",
                    "event_id":row[0],"dispatch_ai":False}
        return {"status":"new_signal_observed" if inserted else "duplicate_signal_observation",
                "event_id":event["event_id"],"dispatch_ai":False}

    def count(self):
        with closing(self._connect()) as db:
            return db.execute("SELECT COUNT(*) FROM signal_observations").fetchone()[0]

