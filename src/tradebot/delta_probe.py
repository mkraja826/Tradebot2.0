"""Non-trading integration diagnostics for Delta Exchange INDIA DEMO.

No method in this module can submit, cancel or modify an order. Diagnostics
never print credentials, wallet amounts, positions, account IDs or order IDs.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from tradebot.delta import DeltaDemo, DEMO_API, DeltaError
from tradebot.market import _prices, _age_seconds, MarketDataError


class ProbeError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def check_public(exchange, *, now=None) -> dict:
    instant = now or datetime.now(timezone.utc)
    _require(getattr(exchange, "base_url", None) == DEMO_API,
             "Refusing to inspect non-India-demo exchange")

    ticker = exchange.ticker("BTCUSD")
    _require(isinstance(ticker, dict) and ticker.get("symbol") == "BTCUSD",
             "BTCUSD ticker response missing or invalid")
    quote = ticker.get("quotes")
    _require(isinstance(quote, dict), "Ticker quote structure missing")

    book = exchange.btc_orderbook(depth=10)
    bid, ask = _prices(book)
    age = _age_seconds(book.get("last_updated_at"), instant)
    _require(age <= 120, "Order book timestamp is stale")

    end = int(instant.timestamp())
    candles = exchange.candles(symbol="BTCUSD", resolution="5m",
                               start=end-3*3600, end=end)
    _require(isinstance(candles, list) and len(candles) > 0,
             "No BTCUSD candles in public feed")
    tail = candles[-1]
    _require(isinstance(tail, dict) and all(
        key in tail for key in ("time", "open", "high", "low", "close", "volume")
    ), "Malformed public candle")

    # Report only schemas/counts/statuses, never prices or account data.
    return {"environment": "delta-india-demo",
            "public_api": "passed",
            "ticker": "BTCUSD",
            "ticker_response": "valid",
            "orderbook_response": "valid",
            "orderbook_recent": True,
            "candles_returned": len(candles),
            "orders_submitted": False}


def check_authenticated(exchange) -> dict:
    _require(getattr(exchange, "base_url", None) == DEMO_API,
             "Refusing non-demo credentials")
    _require(getattr(exchange, "allow_orders", None) is False,
             "Read-only probe requires order mutations disabled")

    wallet = exchange.wallet_balances()
    balances = wallet.get("balances")
    _require(isinstance(balances, list), "Demo balances malformed")
    _require(all(isinstance(b, dict) and "asset_symbol" in b
                 and "available_balance" in b for b in balances),
             "Demo wallet fields malformed")

    orders = exchange.open_orders()
    _require(isinstance(orders, list), "Demo open orders malformed")
    _require(all(isinstance(o, dict) and o.get("product_symbol")
                 and o.get("product_id") is not None for o in orders),
             "Demo open order identity fields missing")

    positions = exchange.btc_positions()
    _require(isinstance(positions, list), "Demo BTC positions malformed")
    _require(all(isinstance(p, dict) and "size" in p for p in positions),
             "Demo BTC position schema malformed")

    # Numeric values, IDs and even exact exposure are deliberately omitted.
    return {"environment": "delta-india-demo",
            "authenticated_read": "passed",
            "wallet_schema": "valid",
            "orders_schema": "valid",
            "positions_schema": "valid",
            "orders_submitted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Delta INDIA DEMO read-only API probe")
    parser.add_argument("--authenticated", action="store_true",
                        help="Also test signed wallet, orders and BTC positions GETs")
    parser.add_argument("--full-snapshot", action="store_true",
                        help="Validate BTC options, futures, Greeks and 5m analysis pipeline")
    args = parser.parse_args()

    if args.authenticated and (not os.getenv("DELTA_DEMO_API_KEY")
                               or not os.getenv("DELTA_DEMO_API_SECRET")):
        parser.error("Both Delta India demo API credentials are required")

    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    try:
        public = check_public(exchange)
        if args.full_snapshot:
            from tradebot.market import collect_market_snapshot
            snapshot = collect_market_snapshot(exchange, include_balances=False)
            public["market_intelligence"] = {
                "pipeline": "passed",
                "btc_derivatives": snapshot["quote_counts"]["catalog_btc_contracts"],
                "futures_quotes": len(snapshot["futures"]),
                "options_quotes": len(snapshot["options"]),
                "usable_quotes": snapshot["quote_counts"]["usable_quotes"],
                "candles_analyzed": len(snapshot["technical"]["last_24"]),
                "no_accounts_read": True,
                "orders_submitted": False,
            }
        if args.authenticated:
            public["account"] = check_authenticated(exchange)
        else:
            public["account"] = {"authenticated_read": "not_requested"}
    except (DeltaError, MarketDataError, ProbeError):
        # Never leak exception details from authenticated API responses in CI.
        print("Delta India demo diagnostic failed. Review endpoint or "
              "credential configuration securely.")
        raise SystemExit(1) from None

    print(json.dumps(public, indent=2))


if __name__ == "__main__":
    main()
