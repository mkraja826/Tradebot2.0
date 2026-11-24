"""Read-only verification that a dedicated Delta India demo account is flat.

This tool NEVER posts, cancels, or modifies an exchange order. It reads remote
BTC positions and every open order and refuses to claim flatness when the
exchange response is missing or malformed.
"""
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from time import sleep

from tradebot.delta import DeltaDemo, DeltaError


def check_flat(exchange: DeltaDemo) -> dict:
    open_orders = exchange.open_orders()
    positions = exchange.btc_positions()
    if not isinstance(open_orders, list) or not isinstance(positions, list):
        raise ValueError("Malformed order or position response")
    active = 0
    for position in positions:
        try:
            size = Decimal(str(position["size"]))
        except (KeyError, TypeError, InvalidOperation, ValueError):
            raise ValueError("Cannot verify BTC position size") from None
        if not size.is_finite():
            raise ValueError("Non-finite BTC position size")
        if size != 0:
            active += 1
    return {
        "environment": "delta-india-demo",
        "orders_submitted_by_verifier": False,
        "btc_open_positions": active,
        "account_open_orders": len(open_orders),
        "verified_flat": active == 0 and len(open_orders) == 0,
    }


def main() -> None:
    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    try:
        first = check_flat(exchange)
        if first["verified_flat"]:
            sleep(2)
            latest = check_flat(exchange)
        else:
            latest = first
    except (ValueError, DeltaError, KeyError, TypeError):
        print(json.dumps({
            "environment": "delta-india-demo",
            "verified_flat": False,
            "orders_submitted_by_verifier": False,
            "error": "Cannot safely verify demo account orders and BTC positions",
        }, indent=2))
        raise SystemExit(2) from None
    print(json.dumps(latest, indent=2))
    if not latest["verified_flat"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
