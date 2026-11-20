"""Read-only Delta India Demo service-upgrade safety gate.

Does not install, restart, disable, cancel, close, open orders, or call AI.
A green report proves only the listed prerequisites, NOT complete trade
readiness, data quality, financial reconciliation, or deployment safety.
"""
import argparse
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3

from tradebot.delta import DEMO_API, DeltaDemo

SAFE_TERMINAL = frozenset({
    "rejected_no_order", "aborted_flat", "flat_verified",
    "cancelled_flat_verified",
})
MARKETS = ("BTCUSD", "XAUTUSD")


def _decimal(value):
    if isinstance(value, bool):
        raise ValueError("invalid broker quantity")
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid broker quantity") from None
    if not n.is_finite():
        raise ValueError("nonfinite broker quantity")
    return n


def _receipt_states(root, symbol):
    name = "fire-ops.sqlite" if symbol == "BTCUSD" else "fire-xaut.sqlite"
    file = root / name
    if not file.is_file() or file.is_symlink():
        raise ValueError("missing or untrusted receipt file")
    # URI mode=ro prevents creation and prevents accidental migrations.
    with closing(sqlite3.connect(file.resolve().as_uri() + "?mode=ro",
                                 uri=True, timeout=5)) as db:
        db.execute("PRAGMA query_only = ON")
        requests = db.execute("SELECT press,status FROM fire_requests").fetchall()
        # FIRE has a separate durable entry ledger. An old unconfirmed entry
        # can block all future orders even when the parent request is flat.
        has_entries = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='fire_entries'"
        ).fetchone()
        entries = (db.execute("SELECT press,status FROM fire_entries").fetchall()
                   if has_entries else [])
    allowed = SAFE_TERMINAL | {
        "requested", "reasoning", "preflight", "submitting",
        "reconciling", "verifying_protection", "protected_active",
        "exposure_unknown",
    }
    by_press = {}
    for press, status in requests:
        if (type(press) is not str or not press
                or type(status) is not str or status not in allowed):
            raise ValueError("unexpected FIRE receipt state")
        by_press[press] = status
    unresolved = {press for press, status in requests if status not in SAFE_TERMINAL}
    allowed_entry = {"submitting", "unconfirmed", "accepted",
                     "filled", "cancelled", "flat_verified"}
    for press, status in entries:
        if (type(press) is not str or press not in by_press
                or type(status) is not str or status not in allowed_entry):
            raise ValueError("orphaned or unexpected broker entry state")
        if status in ("submitting", "unconfirmed", "accepted"):
            unresolved.add(press)
    return len(unresolved)


def audit_demo_upgrade(exchange, data_dir):
    """Return sanitized, fail-closed deployment assessment using GETs only."""
    out = {
        "environment": "delta-india-demo",
        "mode": "read_only",
        "order_mutations": False,
        "ai_calls": 0,
        "broker_positions": None,
        "realtime_fire_positions": {},
        "broker_open_orders": None,
        "unresolved_fire_receipts": None,
        "leverage": {},
        "safe_to_stage_execution_restart": False,
        "safe_to_enable_fire": False,
        "blockers": [],
    }
    blockers = out["blockers"]
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(
            exchange, "allow_orders", None) is not False:
        blockers.append("read_only_delta_demo_client_required")
        return out

    try:
        # Unfiltered /v2/positions is invalid on Delta India Demo (HTTP 400).
        # The margined endpoint is account-wide but may lag up to 10 seconds.
        # Independently check both FIRE markets in real time below.
        result = exchange._request("GET", "/v2/positions/margined", auth=True)["result"]
        if not isinstance(result, list):
            raise ValueError("invalid account-wide margined position list")
        active = 0
        for row in result:
            if (not isinstance(row, dict) or
                    type(row.get("product_id")) is not int or row["product_id"] <= 0):
                raise ValueError("unidentified account position")
            size = _decimal(row.get("size"))
            if size != size.to_integral_value():
                raise ValueError("fractional account position")
            if size:
                active += 1
        out["broker_positions"] = active
        if active:
            blockers.append("account_has_open_positions")
    except Exception:
        blockers.append("account_positions_not_verified")

    try:
        orders = exchange.open_orders()
        if not isinstance(orders, list) or any(
                not isinstance(o, dict) or not o.get("id") for o in orders):
            raise ValueError("incomplete or malformed open orders")
        out["broker_open_orders"] = len(orders)
        if orders:
            blockers.append("account_has_open_orders")
    except Exception:
        blockers.append("account_orders_not_verified")

    unresolved = 0
    receipts_good = True
    root = Path(data_dir).resolve()
    for symbol in MARKETS:
        try:
            unresolved += _receipt_states(root, symbol)
        except (sqlite3.Error, ValueError, OSError):
            receipts_good = False
            blockers.append("fire_receipts_not_verified_" + symbol.lower())
    if receipts_good:
        out["unresolved_fire_receipts"] = unresolved
        if unresolved:
            blockers.append("unresolved_fire_receipts")

    for symbol in MARKETS:
        try:
            product = exchange._request("GET", "/v2/products/" + symbol)["result"]
            if (not isinstance(product, dict) or product.get("symbol") != symbol
                    or product.get("contract_type") != "perpetual_futures"
                    or product.get("notional_type") != "vanilla"
                    or (product.get("settling_asset") or {}).get("symbol") != "USD"
                    or type(product.get("id")) is not int or product["id"] <= 0):
                raise ValueError("product terms not verified")
            setting = exchange._request(
                "GET", f"/v2/products/{product['id']}/orders/leverage",
                auth=True)["result"]
            if not isinstance(setting, dict) or str(
                    setting.get("product_id", product["id"])) != str(product["id"]):
                raise ValueError("leverage product mismatch")
            leverage = _decimal(setting["leverage"])
            if leverage <= 0:
                raise ValueError("invalid broker leverage")
            out["leverage"][symbol] = str(leverage)
            if leverage > 20:
                blockers.append("broker_leverage_above_20x_" + symbol.lower())
        except Exception:
            blockers.append("broker_leverage_not_verified_" + symbol.lower())
            continue
        try:
            # Real-time positions require product_id or underlying symbol.
            live = exchange._request(
                "GET", "/v2/positions",
                params={"product_id": product["id"]}, auth=True
            )["result"]
            if isinstance(live, dict):
                if str(live.get("product_id", product["id"])) != str(product["id"]):
                    raise ValueError("real-time product mismatch")
                rows = [live]
            elif isinstance(live, list):
                rows = live
            else:
                raise ValueError("invalid real-time positions")
            if any(not isinstance(row, dict) or str(
                    row.get("product_id", product["id"])) != str(product["id"])
                   for row in rows):
                raise ValueError("unexpected real-time position")
            sizes = [_decimal(row.get("size")) for row in rows]
            if any(size != size.to_integral_value() for size in sizes):
                raise ValueError("fractional live positions")
            if sum(bool(size) for size in sizes) > 1:
                raise ValueError("multiple selected-market positions")
            total = sum(sizes)
            out["realtime_fire_positions"][symbol] = int(total)
            if total:
                blockers.append("realtime_market_exposure_" + symbol.lower())
        except Exception:
            blockers.append("realtime_position_not_verified_" + symbol.lower())

    # A single flat preflight is preliminary: repeat after at least 10 seconds
    # because the account-wide margined endpoint can lag a new fill.
    # An upgrade may be staged ONLY if every monitored market is broker-flat,
    # all pending orders are absent, and all FIRE stores have terminal states.
    # High leverage is separately disqualifying for enabling new entries.
    stage_blockers = {
        "account_has_open_positions", "account_positions_not_verified",
        "account_has_open_orders", "account_orders_not_verified",
        "fire_receipts_not_verified_btcusd", "fire_receipts_not_verified_xautusd",
        "unresolved_fire_receipts",
        "realtime_market_exposure_btcusd",
        "realtime_market_exposure_xautusd",
        "realtime_position_not_verified_btcusd",
        "realtime_position_not_verified_xautusd",
    }
    out["safe_to_stage_execution_restart"] = not any(
        b in stage_blockers for b in blockers)
    # Deliberately NEVER authorizes FIRE. Equity history and historical
    # data checks require separate commissioning.
    out["safe_to_enable_fire"] = False
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    options = parser.parse_args(argv)
    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False)
    report = audit_demo_upgrade(exchange, options.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["safe_to_stage_execution_restart"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
