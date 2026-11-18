"""SQLite audit ledger for confirmed Delta demo BTC fills and fees.

A confirmed fill is different from an order request. Commission totals are
grouped by actual settling asset and never added across currencies.
Net equity changes are NOT interpreted as realized trade profit.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3


class LedgerError(ValueError):
    pass


def _number(raw, field):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise LedgerError(f"Missing/invalid {field}") from exc
    if not value.is_finite():
        raise LedgerError(f"Non-finite {field}")
    return value


def _normalize(fill):
    if not isinstance(fill, dict):
        raise LedgerError("Expected a fill object")
    symbol = fill.get("product_symbol")
    if not isinstance(symbol, str) or not symbol.upper().startswith(
        ("BTC", "C-BTC-", "P-BTC-")
    ):
        raise LedgerError("Non-BTC fill rejected")
    identifier = fill.get("id")
    if not isinstance(identifier, (str, int)) or not str(identifier).strip():
        raise LedgerError("Fill must have exchange ID")
    settling_asset = fill.get("settling_asset_symbol")
    if not isinstance(settling_asset, str) or not settling_asset:
        raise LedgerError("Fill settling asset unknown")
    side = fill.get("side")
    if side not in ("buy", "sell"):
        raise LedgerError("Malformed fill side")
    try:
        at_us = int(fill["created_at"])
    except (KeyError, ValueError, TypeError) as exc:
        raise LedgerError("Malformed fill timestamp") from exc
    if at_us <= 0:
        raise LedgerError("Invalid fill timestamp")
    size = _number(fill.get("size"), "fill size")
    price = _number(fill.get("price"), "fill price")
    commission = _number(fill.get("commission"), "fill commission")
    if size <= 0 or price <= 0:
        raise LedgerError("Invalid positive size/price")
    notional = fill.get("notional")
    if notional is not None:
        notional = _number(notional, "fill notional")
        if notional < 0:
            raise LedgerError("Invalid notional")
    return (
        str(identifier), at_us, symbol, side, str(size), str(price),
        str(commission), settling_asset,
        str(notional) if notional is not None else None,
        str(fill.get("order_id") or ""), json.dumps(fill, separators=(",", ":")),
    )


def _setup(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fills (
            id TEXT PRIMARY KEY,
            at_us INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            size TEXT NOT NULL,
            price TEXT NOT NULL,
            commission TEXT NOT NULL,
            settling_asset TEXT NOT NULL,
            notional TEXT,
            order_id TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS fills_time ON fills(at_us)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equity_snapshots (
            captured_at TEXT PRIMARY KEY,
            net_equity TEXT NOT NULL
        )
    """)


def ingest_fills(path: str, fills: list[dict]) -> dict:
    """Atomic append and ID-based de-duplication across repeated fetches."""
    rows = [_normalize(fill) for fill in fills]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        _setup(conn)
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO fills
                (id, at_us, symbol, side, size, price, commission,
                 settling_asset, notional, order_id, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        added = conn.total_changes - before
    return {"received": len(rows), "new_fills": added,
            "duplicate_fills": len(rows) - added}


def record_equity(path: str, net_equity, *, at=None):
    value = _number(net_equity, "account equity")
    if value < 0:
        raise LedgerError("Net equity must be nonnegative")
    instant = at or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise LedgerError("Timestamp must be timezone-aware")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        _setup(conn)
        conn.execute("INSERT OR REPLACE INTO equity_snapshots VALUES (?,?)",
                     (instant.astimezone(timezone.utc).isoformat(), str(value)))


def fill_summary(path: str, *, since_us: int | None = None) -> dict:
    """Confirmed fill/commission metrics only. NOT a realized P&L report."""
    target = Path(path)
    if not target.exists():
        return {"confirmed_btc_fills": 0, "fees_by_asset": {},
                "symbols": {}, "is_realized_pnl": False}
    with sqlite3.connect(target) as conn:
        _setup(conn)
        if since_us is None:
            rows = conn.execute(
                "SELECT symbol, side, commission, settling_asset FROM fills"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT symbol, side, commission, settling_asset FROM fills "
                "WHERE at_us >= ?", (since_us,)
            ).fetchall()
    fees, symbols = {}, {}
    for symbol, side, fee, asset in rows:
        fees[asset] = fees.get(asset, Decimal("0")) + Decimal(fee)
        count = symbols.setdefault(symbol, {"buy_fills": 0, "sell_fills": 0})
        count[f"{side}_fills"] += 1
    return {
        "confirmed_btc_fills": len(rows),
        "fees_by_asset": {asset: str(total) for asset, total in sorted(fees.items())},
        "symbols": symbols,
        "is_realized_pnl": False,
        "note": "Fees and fill counts only; mark-to-market equity and realized P&L "
                "require separate reconciliation, including funding/transfers.",
    }
