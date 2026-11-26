"""Read-only BTC liquidation research MCP tools; operator-configured snapshots."""
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from .tb2_backtest_tools import check_window, integer, signatures
from .liquidation_ema9 import run

VERSION = "tb2-liquidation-v1"
SOURCE = "bybit_public_linear_BTCUSDT"
Market = Literal["BTCUSD", "XAUTUSD"]


def response(**kwargs):
    return dict(version=VERSION, execution_effect="none", source=SOURCE, **kwargs)


@contextmanager
def reader(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        yield db


def coverage(path, query):
    try:
        with reader(path) as db:
            n, first, last = db.execute(query).fetchone()
            return dict(status="observed" if n else "empty_archive", rows=n,
                        first_ms=first, last_ms=last, snapshot_mtime_ns=path.stat().st_mtime_ns)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return dict(status="unavailable_or_invalid", error_type=type(exc).__name__)


def page(path, sql, params, names, limit, offset, transform=None):
    try:
        before = signatures([path])
        with reader(path) as db:
            rows = db.execute(sql, (*params, limit + 1, offset)).fetchall()
        if before != signatures([path]):
            return response(status="snapshot_changed_retry")
        items = [dict(zip(names, row)) for row in rows[:limit]]
        if transform:
            items = [transform(row) for row in items]
        return response(status="observed" if items else "no_observed_rows",
                        items=items, returned=len(items),
                        next_offset=offset + limit if len(rows) > limit else None,
                        snapshot_mtime_ns=before[0][2],
                        coverage="event_completeness_unverified")
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
        return response(status="research_data_unavailable_or_invalid", error_type=type(exc).__name__)


def positioning_row(row):
    p = json.loads(row.pop("payload"))
    if (not isinstance(p, dict) or p.get("symbol") != "BTCUSDT"
            or p.get("source_ms") != row["source_ms"] or p.get("received_ms") != row["received_ms"]):
        raise ValueError("invalid positioning identity")
    keys = ("open_interest_btc_both_sides", "indicative_funding_fraction",
            "indicative_funding_bps", "funding_interval_hours", "next_funding_ms",
            "mark_usdt", "index_usdt")
    return {**row, **{k:p.get(k) for k in keys}}


def register_liquidation_tools(mcp, *, data_dir, liquidation_dir):
    """Register only against fixed operator-provisioned read-only databases."""
    root = Path(data_dir).resolve() / "BTCUSD"
    reference = Path(liquidation_dir).resolve()
    events = reference / "events.sqlite"
    positioning = reference / "positioning.sqlite"
    hypotheses = reference / "hypotheses.sqlite"

    def supported(symbol):
        if symbol not in ("BTCUSD", "XAUTUSD"):
            raise ValueError("unsupported demo market")
        return symbol == "BTCUSD"

    def unsupported():
        return dict(version=VERSION, execution_effect="none", symbol="XAUTUSD",
                    status="unavailable", reason="no_verified_XAUT_liquidation_source")

    @mcp.tool()
    def liquidation_status(symbol: Market="BTCUSD"):
        """Inspect reference archive coverage and last recorded collector session, not live health."""
        if not supported(symbol):
            return unsupported()
        results = {
            "events":coverage(events,"SELECT count(*),min(event_ms),max(event_ms) FROM events"),
            "positioning":coverage(positioning,"SELECT count(*),min(source_ms),max(source_ms) FROM positioning"),
            "hypotheses":coverage(hypotheses,"SELECT count(*),min(observed_ms),max(observed_ms) FROM observations"),
        }
        try:
            with reader(events) as db:
                row = db.execute("SELECT started_ms,subscribed_ms,heartbeat_ms,ended_ms,status FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
                session = dict(zip(("started_ms","subscribed_ms","heartbeat_ms","ended_ms","status"),row)) if row else None
                duplicates = db.execute("SELECT coalesce(sum(duplicate_count),0) FROM batches").fetchone()[0]
        except (sqlite3.Error,OSError,ValueError):
            session = duplicates = None
        return response(status="archive_inspected", symbol=symbol, archives=results,
                        last_recorded_session=session, duplicate_batches=duplicates,
                        live_health_verified=False, coverage="event_completeness_unverified",
                        limitations=["Snapshot heartbeat is historical; no live service access.",
                                     "No rows is not proof of zero market liquidations."])

    @mcp.tool()
    def liquidation_history(symbol: Market, start: int, end: int, limit: int=100, offset: int=0):
        """Read archived reference events, UTC seconds, end exclusive, bounded page."""
        if not supported(symbol):
            return unsupported()
        check_window(start,end);integer(limit,1,500);integer(offset,0,1000000)
        return page(events,
            "SELECT e.batch_id,e.ordinal,e.event_ms,b.received_ms,e.side,e.size,e.bankruptcy_price "
            "FROM events e JOIN batches b ON e.batch_id=b.id "
            "WHERE e.event_ms>=? AND e.event_ms<? AND b.received_ms<? "
            "ORDER BY e.event_ms,e.batch_id,e.ordinal LIMIT ? OFFSET ?",
            (start*1000,end*1000,end*1000),
            ("batch_id","ordinal","event_ms","received_ms","liquidated_position_side","size_btc","bankruptcy_price_usdt"),
            limit,offset)

    @mcp.tool()
    def positioning_history(symbol: Market, start: int, end: int, limit: int=100, offset: int=0):
        """Read archived Bybit BTC open interest and indicative funding, not Delta funding."""
        if not supported(symbol):
            return unsupported()
        check_window(start,end);integer(limit,1,500);integer(offset,0,45000)
        return page(positioning,
            "SELECT source_ms,received_ms,payload FROM positioning "
            "WHERE source_ms>=? AND source_ms<? AND received_ms<? "
            "ORDER BY source_ms LIMIT ? OFFSET ?",
            (start*1000,end*1000,end*1000),
            ("source_ms","received_ms","payload"),limit,offset,positioning_row)

    @mcp.tool()
    def liquidation_ema_backtest(symbol: Market, start: int, split: int, end: int):
        """Run BTC liquidation entry replay versus fixed/EMA9 V8 exits; summaries only."""
        if not supported(symbol):
            return unsupported()
        check_window(start,end)
        if type(split) is not int or not start < split < end:
            raise ValueError("split must be strictly inside window")
        paths = [root/"market.sqlite",hypotheses]
        try:
            before = signatures(paths)
            result = run(root,hypotheses,start,split,end)
            if before != signatures(paths):
                return response(status="snapshot_changed_retry")
            result["eligible_entries"] = len(result.pop("trades"))
            if result["observation_count"] == 0:
                result["status"] = "no_archived_observations_in_window"
            result["snapshot_mtime_ns"] = {p.name:s[2] for p,s in zip(paths,before)}
            return result
        except (sqlite3.Error,OSError,ValueError,TypeError,KeyError,ArithmeticError) as exc:
            return response(status="research_data_unavailable_or_invalid",error_type=type(exc).__name__)
