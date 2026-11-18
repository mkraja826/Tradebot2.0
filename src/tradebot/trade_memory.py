"""Append-only evidence and reversible Kimi research memory for Delta Demo BTCUSD.

Learning cannot execute trades or modify GPT-6's system instructions.
Evidence and hypotheses are separate; no unverified lesson enters FIRE.
"""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4


class MemoryError(ValueError):
    pass


# Never persist upstream raw responses, credentials, wallets, account IDs or PII.
# Each event is only a bounded, explicitly selected factual observation.
EVENT_FIELDS = {
    "gpt6_proposal": frozenset({
        "model", "direction", "contracts", "stop_loss", "take_profit",
        "bid", "ask", "snapshot_at", "snapshot_sha256",
    }),
    "position_first_observed": frozenset({
        "symbol", "product_id", "size", "entry_price", "mark_price",
        "bid", "ask", "observed_at",
    }),
    "position_observed": frozenset({
        "symbol", "product_id", "size", "entry_price", "mark_price",
        "bid", "ask", "observed_at",
    }),
    "position_closed_observed": frozenset({
        "symbol", "product_id", "prior_size", "mark_price", "bid", "ask",
        "observed_at", "realized_pnl_verified",
    }),
    "exchange_uncertain": frozenset({"reason", "observed_at"}),
    "confirmed_fill": frozenset({
        "fill_id", "order_id", "product_id", "symbol", "side",
        "size", "price", "fee", "fee_asset", "observed_at",
    }),
}
MAX_TEXT = 150


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _scalar(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > MAX_TEXT:
            raise MemoryError("Evidence field exceeds bounded text limit")
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        try:
            if not Decimal(str(value)).is_finite():
                raise MemoryError("Non-finite evidence number")
        except InvalidOperation:
            raise MemoryError("Invalid evidence number") from None
        return value
    raise MemoryError("Evidence must be a scalar; raw broker/model bodies forbidden")


def _safe_name(value, field):
    if (not isinstance(value, str) or not 1 <= len(value) <= 96
            or not all(ch.isalnum() or ch in "_-:." for ch in value)):
        raise MemoryError("Invalid " + field)
    return value


class TradeMemory:
    def __init__(self, path="data/trade-learning.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise MemoryError("Refusing symlinked learning database")
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL,
                    kind TEXT NOT NULL, observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_trade_events
                    ON events(trade_id, observed_at, event_id);
                CREATE TABLE IF NOT EXISTS lessons (
                    lesson_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL,
                    review_key TEXT NOT NULL, created_at TEXT NOT NULL,
                    hypothesis TEXT NOT NULL, counterevidence TEXT NOT NULL,
                    applicable_when TEXT NOT NULL, confidence REAL NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate'
                    CHECK(status IN ('candidate','validated','retired')),
                    UNIQUE(review_key, hypothesis)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    review_key TEXT PRIMARY KEY, trade_id TEXT NOT NULL,
                    phase TEXT NOT NULL, started_at TEXT NOT NULL,
                    status TEXT NOT NULL, completed_at TEXT,
                    token_count INTEGER
                );
                CREATE TABLE IF NOT EXISTS position_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    trade_id TEXT, active INTEGER NOT NULL,
                    last_size TEXT, last_mark TEXT, last_observed TEXT,
                    last_review_mark TEXT, last_review_at TEXT
                );
                CREATE TRIGGER IF NOT EXISTS learning_events_immutable_update
                    BEFORE UPDATE ON events BEGIN
                    SELECT RAISE(ABORT, 'Evidence cannot be edited');
                END;
                CREATE TRIGGER IF NOT EXISTS learning_events_immutable_delete
                    BEFORE DELETE ON events BEGIN
                    SELECT RAISE(ABORT, 'Evidence cannot be deleted');
                END;
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return closing(db)

    def append_event(self, trade_id, kind, data, *, event_id=None, observed_at=None):
        _safe_name(trade_id, "trade ID")
        if kind not in EVENT_FIELDS or not isinstance(data, dict):
            raise MemoryError("Unknown evidence kind or malformed data")
        if not data or set(data) - EVENT_FIELDS[kind]:
            raise MemoryError("Evidence includes unsupported fields")
        safe = {k: _scalar(v) for k, v in data.items()}
        payload = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False)
        observed_at = observed_at or utcnow()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        event_id = _safe_name(event_id or ("evt-" + uuid4().hex), "event ID")
        with self._db() as db:
            try:
                db.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?,?)",
                    (event_id, trade_id, kind, observed_at, payload, digest),
                )
                db.commit()
                return event_id
            except sqlite3.IntegrityError:
                old = db.execute(
                    "SELECT trade_id, kind, observed_at, payload_sha256 "
                    "FROM events WHERE event_id=?", (event_id,),
                ).fetchone()
                if not old or (old["trade_id"], old["kind"],
                               old["payload_sha256"]) != (trade_id, kind, digest):
                    raise MemoryError("Conflicting duplicate evidence ID") from None
                return event_id

    def events(self, trade_id, *, limit=60):
        _safe_name(trade_id, "trade ID")
        if not 1 <= limit <= 150:
            raise MemoryError("Invalid event limit")
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE trade_id=? "
                "ORDER BY observed_at DESC, event_id DESC LIMIT ?", (trade_id, limit)
            ).fetchall()
        return [dict(event_id=row["event_id"], kind=row["kind"],
                     observed_at=row["observed_at"], details=json.loads(row["payload"]))
                for row in reversed(rows)]

    def reserve_review(self, review_key, trade_id, phase, *, max_daily=12):
        """Durable paid-call idempotency; do not retry ambiguous/failed requests."""
        _safe_name(review_key, "review ID")
        _safe_name(trade_id, "trade ID")
        if phase not in ("entry", "checkpoint", "exit"):
            raise MemoryError("Invalid review phase")
        instant = utcnow()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM reviews WHERE review_key=?", (review_key,)).fetchone():
                return False
            count = db.execute(
                "SELECT COUNT(*) FROM reviews WHERE started_at >= ?",
                (instant[:10],)
            ).fetchone()[0]
            if count >= max_daily:
                return False
            db.execute(
                "INSERT INTO reviews(review_key,trade_id,phase,started_at,status) "
                "VALUES (?,?,?,?,?)", (review_key, trade_id, phase, instant, "started"),
            )
            db.commit()
            return True

    def finish_review(self, review_key, status, *, token_count=None):
        _safe_name(review_key, "review ID")
        if status not in ("completed", "rejected", "provider_failed"):
            raise MemoryError("Invalid review status")
        if token_count is not None and (type(token_count) is not int or token_count < 0):
            raise MemoryError("Invalid token count")
        with self._db() as db:
            db.execute(
                "UPDATE reviews SET status=?, completed_at=?, token_count=? "
                "WHERE review_key=? AND status='started'",
                (status, utcnow(), token_count, review_key)
            )
            db.commit()

    def store_candidates(self, review_key, trade_id, candidates):
        """All Kimi output starts as a hypothesis, never as a validated fact."""
        _safe_name(review_key, "review ID")
        _safe_name(trade_id, "trade ID")
        if not isinstance(candidates, list) or len(candidates) > 3:
            raise MemoryError("Expected up to three hypotheses")
        known = {event["event_id"] for event in self.events(trade_id, limit=150)}
        prepared = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise MemoryError("Malformed lesson")
            if set(candidate) != {"hypothesis", "counterevidence",
                                  "applicable_when", "confidence", "evidence_refs"}:
                raise MemoryError("Incomplete lesson or extra fields")
            for key in ("hypothesis", "counterevidence", "applicable_when"):
                if (not isinstance(candidate[key], str) or
                        not 5 <= len(candidate[key].strip()) <= 350):
                    raise MemoryError("Lesson text missing or too long")
            try:
                confidence = Decimal(str(candidate["confidence"]))
            except (ValueError, TypeError, InvalidOperation):
                raise MemoryError("Invalid lesson confidence") from None
            if not confidence.is_finite() or not 0 <= confidence <= 1:
                raise MemoryError("Lesson confidence outside 0..1")
            refs = candidate["evidence_refs"]
            if (not isinstance(refs, list) or not 1 <= len(refs) <= 8 or
                    len(set(refs)) != len(refs) or any(ref not in known for ref in refs)):
                raise MemoryError("Lesson cites unknown trade evidence")
            prepared.append((uuid4().hex, trade_id, review_key, utcnow(),
                             candidate["hypothesis"].strip(),
                             candidate["counterevidence"].strip(),
                             candidate["applicable_when"].strip(),
                             float(confidence), json.dumps(refs), "candidate"))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT trade_id,status FROM reviews WHERE review_key=?", (review_key,)
            ).fetchone()
            if row is None or row["trade_id"] != trade_id or row["status"] != "started":
                raise MemoryError("Review not reserved or already finalized")
            for record in prepared:
                db.execute("INSERT OR IGNORE INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?)", record)
            db.commit()
        return len(prepared)

    def lessons(self, *, status="candidate", limit=20):
        if status not in ("candidate", "validated", "retired") or not 1 <= limit <= 50:
            raise MemoryError("Invalid lesson query")
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM lessons WHERE status=? "
                "ORDER BY created_at DESC LIMIT ?", (status, limit)
            ).fetchall()
        return [dict(row) | {"evidence_refs": json.loads(row["evidence_refs"])}
                for row in rows]

    def fire_advisories(self, *, limit=3):
        """Only validated lessons; default is empty even if Kimi wrote candidates."""
        if not 1 <= limit <= 3:
            raise MemoryError("Advisory limit must be 1..3")
        return [
            {k: item[k] for k in (
                "lesson_id", "hypothesis", "counterevidence",
                "applicable_when", "confidence", "evidence_refs"
            )} for item in self.lessons(status="validated", limit=limit)
        ]

    def watch_state(self):
        with self._db() as db:
            row = db.execute("SELECT * FROM position_state WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def save_watch_state(self, *, trade_id, active, size, mark,
                         observed_at, review_mark=None, review_at=None):
        if trade_id is not None:
            _safe_name(trade_id, "trade ID")
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO position_state VALUES (1,?,?,?,?,?,?,?)",
                (trade_id, int(bool(active)), str(size) if size is not None else None,
                 str(mark) if mark is not None else None, observed_at,
                 str(review_mark) if review_mark is not None else None, review_at)
            )
            db.commit()


def public_learning_summary(path):
    """Bounded read-only dashboard projection; never opens the DB for writes."""
    path = Path(path)
    initial = {
        "status": "not_initialized", "active_position": False,
        "evidence_events": 0, "candidate_lessons": 0,
        "validated_lessons": 0, "recent_hypotheses": [],
        "gpt6_memory_injection_enabled": False,
        "kimi_can_place_orders": False,
    }
    if not path.is_file() or path.is_symlink():
        return initial
    from urllib.parse import quote
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=1) as db:
            active = db.execute(
                "SELECT active, last_observed FROM position_state WHERE singleton=1"
            ).fetchone()
            events = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            candidates = db.execute(
                "SELECT COUNT(*) FROM lessons WHERE status='candidate'").fetchone()[0]
            validated = db.execute(
                "SELECT COUNT(*) FROM lessons WHERE status='validated'").fetchone()[0]
            rows = db.execute(
                "SELECT hypothesis,counterevidence,applicable_when,confidence,created_at "
                "FROM lessons WHERE status='candidate' "
                "ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
        return {
            "status": "available",
            "active_position": bool(active and active[0]),
            "last_observation_at": active[1] if active else None,
            "evidence_events": events,
            "candidate_lessons": candidates,
            "validated_lessons": validated,
            "recent_hypotheses": [
                {"hypothesis": r[0], "counterevidence": r[1],
                 "applicable_when": r[2], "confidence": r[3],
                 "created_at": r[4]} for r in rows],
            "gpt6_memory_injection_enabled": False,
            "kimi_can_place_orders": False,
        }
    except (sqlite3.Error, OSError):
        return {**initial, "status": "unavailable"}
