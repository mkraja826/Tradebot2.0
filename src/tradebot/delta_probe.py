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


def _safe_get(getter, stage: str):
    """Classify a read-only auth failure without printing provider response.

    Do not include exception text, keys, signatures, request URLs or any
    private account fields in an Actions log.
    """
    from urllib.error import HTTPError
    try:
        return getter()
    except DeltaError as exc:
        cause = exc.__cause__
        if isinstance(cause, HTTPError):
            # Match ONLY documented error categories; never print Delta's
            # response body, contexts, IP addresses or account identifiers.
            known = {
                "invalid_api_key": "INVALID_API_KEY",
                "signatureexpired": "SIGNATURE_EXPIRED",
                "signature mismatch": "SIGNATURE_MISMATCH",
                "unauthorizedapiaccess": "UNAUTHORIZED_API_ACCESS",
                "ip_not_whitelisted_for_api_key": "IP_NOT_WHITELISTED",
                "forbidden": "CDN_FORBIDDEN",
            }
            reason = "UNKNOWN"
            try:
                data = json.loads(cause.read(8192))
                err = data.get("error", "")
                raw = (err.get("code") or err.get("message") or "")
                      if isinstance(err, dict) else err
                if isinstance(raw, str):
                    reason = known.get(raw.strip().lower(), "UNKNOWN")
            except (ValueError, TypeError, AttributeError, OSError):
                pass
            raise ProbeError(
                f"AUTH_STAGE={stage} STATUS=HTTP_{cause.code} CATEGORY={reason}"
            ) from None
        raise ProbeError(f"AUTH_STAGE={stage} STATUS=DELTA_API_REJECTED_OR_UNAVAILABLE") from None


def check_authenticated(exchange) -> dict:
    _require(getattr(exchange, "base_url", None) == DEMO_API,
             "Refusing non-demo credentials")
    _require(getattr(exchange, "allow_orders", None) is False,
             "Read-only probe requires order mutations disabled")

    wallet = _safe_get(exchange.wallet_balances, "wallet")
    balances = wallet.get("balances")
    _require(isinstance(balances, list), "AUTH_STAGE=wallet STATUS=BAD_SCHEMA")
    _require(all(isinstance(b, dict) and "asset_symbol" in b
                 and "available_balance" in b for b in balances),
             "AUTH_STAGE=wallet STATUS=BAD_FIELDS")

    orders = _safe_get(exchange.open_orders, "open_orders")
    _require(isinstance(orders, list), "AUTH_STAGE=open_orders STATUS=BAD_SCHEMA")
    _require(all(isinstance(o, dict) and o.get("product_symbol")
                 and o.get("product_id") is not None for o in orders),
             "AUTH_STAGE=open_orders STATUS=BAD_FIELDS")

    positions = _safe_get(exchange.btc_positions, "positions")
    _require(isinstance(positions, list), "AUTH_STAGE=positions STATUS=BAD_SCHEMA")
    _require(all(isinstance(p, dict) and "size" in p for p in positions),
             "AUTH_STAGE=positions STATUS=BAD_FIELDS")

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
    except ProbeError as exc:
        # Only fixed stage/status markers are permitted for authenticated
        # failures. Never emit the originating HTTP response or its body.
        if args.authenticated and str(exc).startswith("AUTH_STAGE="):
            print(str(exc))
        print("Delta India demo diagnostic failed (sanitized details only).")
        raise SystemExit(1) from None
    except (DeltaError, MarketDataError):
        print("Delta India demo diagnostic failed (no credentials logged).")
        raise SystemExit(1) from None

    print(json.dumps(public, indent=2))


if __name__ == "__main__":
    main()
