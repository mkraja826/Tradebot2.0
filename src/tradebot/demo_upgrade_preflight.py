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
        rows = db.execute("SELECT status FROM fire_requests").fetchall()
    allowed = SAFE_TERMINAL | {
        "requested", "reasoning", "preflight", "submitting",
        "reconciling", "verifying_protection", "protected_active",
        "exposure_unknown",
    }
    if any(type(row[0]) is not str or row[0] not in allowed for row in rows):
        raise ValueError("unexpected FIRE receipt state")
    return sum(status not in SAFE_TERMINAL for (status,) in rows)


def audit_demo_upgrade(exchange, data_dir):
    """Return sanitized, fail-closed deployment assessment using GETs only."""
    out = {
        "environment": "delta-india-demo",
        "mode": "read_only",
        "order_mutations": False,
        "ai_calls": 0,
        "broker_positions": None,
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
        result = exchange._request("GET", "/v2/positions", auth=True)["result"]
        if not isinstance(result, list):
            raise ValueError("global positions must be a complete list")
        active = 0
        for row in result:
            if (not isinstance(row, dict) or
                    not str(row.get("product_id", "")).isdigit()):
                raise ValueError("unidentified account position")
            if _decimal(row.get("size")) != 0:
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

    leverages_ok = True
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
            if leverage > 5:
                leverages_ok = False
                blockers.append("broker_leverage_above_5x_" + symbol.lower())
        except Exception:
            leverages_ok = False
            blockers.append("broker_leverage_not_verified_" + symbol.lower())

    # An upgrade may be staged ONLY if every monitored market is broker-flat,
    # all pending orders are absent, and all FIRE stores have terminal states.
    # High leverage is separately disqualifying for enabling new entries.
    stage_blockers = {
        "account_has_open_positions", "account_positions_not_verified",
        "account_has_open_orders", "account_orders_not_verified",
        "fire_receipts_not_verified_btcusd", "fire_receipts_not_verified_xautusd",
        "unresolved_fire_receipts",
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
