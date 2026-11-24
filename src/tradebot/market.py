"""Validated public BTC snapshot plus optional signed demo-wallet observations.

This module only reads the exchange. It never submits orders. A model may
propose strategies from these observations, but execution must independently
verify quotes, margin, positions and the NYSE trading session.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import log, sqrt
from statistics import pstdev

from tradebot.delta import DeltaError, is_btc_contract
from tradebot.session import session_phase


class MarketDataError(ValueError):
    pass


def _decimal(value, field, *, positive=False):
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite() or (positive and parsed <= 0):
            raise ValueError
        return parsed
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarketDataError(f"Invalid {field}") from exc


def _age_seconds(timestamp, instant: datetime):
    """Delta ticker timestamps use seconds; L2 book timestamps use microseconds."""
    try:
        stamp = float(timestamp)
    except (ValueError, TypeError) as exc:
        raise MarketDataError("Missing or malformed exchange timestamp") from exc
    if stamp > 1e14:
        stamp /= 1_000_000
    elif stamp > 1e11:
        stamp /= 1_000
    age = instant.timestamp() - stamp
    if age < -10 or age > 60 * 60 * 24 * 365:
        raise MarketDataError("Exchange clock is invalid")
    return max(0.0, age)


def _prices(book: dict, symbol="BTCUSD"):
    if book.get("symbol") != symbol:
        raise MarketDataError("Unexpected orderbook market")
    if not isinstance(book.get("buy"), list) or not isinstance(book.get("sell"), list):
        raise MarketDataError("Invalid BTC order book depth")
    if not book["buy"] or not book["sell"]:
        raise MarketDataError("BTC order book is missing bids or asks")
    bids = [_decimal(row["price"], "bid price", positive=True) for row in book["buy"]]
    asks = [_decimal(row["price"], "ask price", positive=True) for row in book["sell"]]
    bid, ask = max(bids), min(asks)
    if bid >= ask:
        raise MarketDataError("BTC order book crossed or locked")
    return bid, ask


def _candles(rows: list[dict], instant: datetime):
    if not rows:
        raise MarketDataError("No BTC candles")
    by_time = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MarketDataError("Malformed candle")
        try:
            moment = int(row["time"])
            op = _decimal(row["open"], "candle open", positive=True)
            hi = _decimal(row["high"], "candle high", positive=True)
            lo = _decimal(row["low"], "candle low", positive=True)
            close = _decimal(row["close"], "candle close", positive=True)
            vol = _decimal(row["volume"], "candle volume")
        except (KeyError, ValueError, TypeError) as exc:
            raise MarketDataError("Malformed BTC candle") from exc
        if lo > min(op, close) or hi < max(op, close) or hi < lo or vol < 0:
            raise MarketDataError("Inconsistent candle OHLCV")
        by_time[moment] = {"time": moment, "open": str(op), "high": str(hi),
                           "low": str(lo), "close": str(close), "volume": str(vol)}
    candles = [by_time[k] for k in sorted(by_time)]
    if len(candles) < 13:
        raise MarketDataError("Not enough BTC candles for analysis")
    # We call the endpoint with 5-minute resolution, so a 1-hour return
    # must span twelve *consecutive* 5-minute intervals.
    last_13 = candles[-13:]
    if any(b["time"] - a["time"] != 300
           for a, b in zip(last_13, last_13[1:])):
        raise MarketDataError("Recent BTC candles have missing or irregular intervals")
    if _age_seconds(candles[-1]["time"], instant) > 11 * 60:
        raise MarketDataError("BTC candle feed is stale")
    closes = [float(c["close"]) for c in candles]
    log_returns = [log(closes[i] / closes[i - 1])
                   for i in range(max(1, len(closes) - 12), len(closes))]
    return {
        "latest": candles[-1],
        "last_24": candles[-24:],
        "return_1h_pct": round((closes[-1] / closes[-13] - 1) * 100, 4),
        "realized_vol_1h_pct": round(pstdev(log_returns) * sqrt(12) * 100, 4),
    }


def _quote(ticker: dict, product: dict, instant: datetime):
    quotes = ticker.get("quotes") or {}
    if not isinstance(quotes, dict):
        quotes = {}
    try:
        age = round(_age_seconds(ticker.get("timestamp"), instant), 1)
    except MarketDataError:
        age = None
    try:
        bid = _decimal(quotes.get("best_bid"), "ticker bid", positive=True)
        ask = _decimal(quotes.get("best_ask"), "ticker ask", positive=True)
        valid_spread = bid < ask
    except MarketDataError:
        bid, ask, valid_spread = None, None, False
    operational = product.get("trading_status", "operational") == "operational"
    usable = bool(valid_spread and age is not None and age <= 60 and operational)
    greeks = ticker.get("greeks") or {}
    if not isinstance(greeks, dict):
        greeks = {}
    return {
        "product_id": product["id"],
        "symbol": product["symbol"],
        "contract_type": product["contract_type"],
        "strike_price": product.get("strike_price"),
        "settlement_time": product.get("settlement_time"),
        "contract_value": product.get("contract_value"),
        "taker_commission_rate": product.get("taker_commission_rate"),
        "mark_price": ticker.get("mark_price"),
        "spot_price": ticker.get("spot_price"),
        "open_interest": ticker.get("oi"),
        "volume": ticker.get("volume"),
        "bid": str(bid) if bid is not None else None,
        "ask": str(ask) if ask is not None else None,
        "bid_iv": quotes.get("bid_iv"),
        "ask_iv": quotes.get("ask_iv"),
        "greeks": {k: greeks.get(k) for k in ("delta", "gamma", "theta", "vega", "rho")},
        "age_seconds": age,
        "usable_quote": usable,
    }


def _balances(raw: dict):
    result = []
    for wallet in raw["balances"]:
        if not isinstance(wallet, dict) or not wallet.get("asset_symbol"):
            raise MarketDataError("Malformed demo wallet balance")
        available = _decimal(wallet.get("available_balance"),
                             "available demo balance")
        if available < 0:
            raise MarketDataError("Negative available demo balance")
        result.append({
            "asset": wallet["asset_symbol"],
            "available_balance": str(available),
            "balance": wallet.get("balance"),
            "blocked_margin": wallet.get("blocked_margin"),
        })
    equity = raw["meta"].get("net_equity")
    if equity is not None:
        equity = str(_decimal(equity, "demo net equity"))
    return {"net_equity": equity, "wallets": result}


def collect_market_snapshot(exchange, *, now: datetime | None = None,
                            include_balances: bool = False) -> dict:
    """Fetch one BTC snapshot. Fail closed on missing/stale core market data.

    Public quotes are never silently replaced with cached prices. Optional
    balances require an authenticated demo key, but this call still cannot
    issue an order.
    """
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Snapshot timestamp must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    products = exchange.products()
    supported = {p["id"]: p for p in products if is_btc_contract(p)}
    if not supported:
        raise MarketDataError("BTC derivative product catalog empty")
    if not any(p["symbol"] == "BTCUSD" for p in supported.values()):
        raise MarketDataError("BTCUSD perpetual contract unavailable")
    tickers = exchange.btc_tickers()
    if not isinstance(tickers, list):
        raise MarketDataError("Malformed BTC ticker feed")
    joined = {}
    for ticker in tickers:
        if not isinstance(ticker, dict):
            continue
        product = supported.get(ticker.get("product_id"))
        if product is None or ticker.get("symbol") != product["symbol"]:
            continue
        joined[product["id"]] = _quote(ticker, product, instant)
    btc = next((q for q in joined.values() if q["symbol"] == "BTCUSD"), None)
    if btc is None or not btc["usable_quote"]:
        raise MarketDataError("BTCUSD ticker missing, stale, or unquotable")
    book = exchange.btc_orderbook(depth=20)
    book_age = _age_seconds(book.get("last_updated_at"), instant)
    if book_age > 60:
        raise MarketDataError("BTC order book stale")
    bid, ask = _prices(book)
    end = int(instant.timestamp())
    # 6h gives enough 5m candles even if a few bars were skipped.
    candle_rows = exchange.candles(symbol="BTCUSD", resolution="5m",
                                  start=end - 6 * 3600, end=end)
    analysis = _candles(candle_rows, instant)
    snapshot = {
        "environment": "delta-india-demo",
        "collected_at": instant.isoformat(),
        "session_phase": session_phase(instant).value,
        "core": {
            "symbol": "BTCUSD", "best_bid": str(bid), "best_ask": str(ask),
            "spread": str(ask - bid),
            "book_age_seconds": round(book_age, 1), "ticker": btc,
        },
        "technical": analysis,
        "futures": [q for q in joined.values() if q["contract_type"]
                    in ("futures", "perpetual_futures")],
        "options": [q for q in joined.values() if q["contract_type"]
                    in ("call_options", "put_options")],
        "quote_counts": {
            "catalog_btc_contracts": len(supported),
            "matched_tickers": len(joined),
            "usable_quotes": sum(bool(q["usable_quote"]) for q in joined.values()),
        },
        "demo_funds": None,
    }
    if include_balances:
        snapshot["demo_funds"] = _balances(exchange.wallet_balances())
    return snapshot
