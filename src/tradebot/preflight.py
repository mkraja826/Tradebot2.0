"""Read-only preflight for AI-generated BTC demo entry plans.

This does not calculate exchange margin for option spreads. Delta's matching
engine is authoritative for available margin and liquidations. Every entry
must be rechecked against live quote and account data immediately before use.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from tradebot.delta import is_btc_contract
from tradebot.market import _age_seconds
from tradebot.session import SessionPhase, entry_phase


class PreflightError(ValueError):
    """A proposal was rejected before placing any orders."""


def _positive(raw) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PreflightError("Account value missing or invalid") from exc
    if not value.is_finite() or value < 0:
        raise PreflightError("Invalid account value")
    return value


@dataclass(frozen=True)
class PreflightReport:
    checked_at: str
    quoted_legs: int
    spendable_demo_assets: tuple[str, ...]
    broker_margin_verified: bool = False


def check_entry(exchange, plan, products, *, now=None, schedule: str = "nyse") -> PreflightReport:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise PreflightError("Timezone-aware clock required")
    if entry_phase(instant, schedule=schedule) != SessionPhase.TRADING:
        raise PreflightError("Outside authorized BTC entry window")
    if not plan.orders:
        return PreflightReport(instant.isoformat(), 0, ())
    allowed = {p["id"]: p for p in products if is_btc_contract(p)}
    to_quote = {}
    for leg in plan.orders:
        if (type(leg.product_id) is not int
                or leg.product_id not in allowed
                or type(leg.size) is not int or leg.size < 1
                or leg.side not in ("buy", "sell")):
            raise PreflightError("AI intent references invalid BTC derivative leg")
        to_quote[leg.product_id] = allowed[leg.product_id]

    # Requery exchange quotes independently of the snapshot presented to AI.
    # A call can fail due to network loss or an expired option; fail closed.
    for product in to_quote.values():
        ticker = exchange.ticker(product["symbol"])
        if ticker.get("symbol") != product["symbol"]:
            raise PreflightError("Fresh ticker contract mismatch")
        try:
            age = _age_seconds(ticker.get("timestamp"), instant)
            quotes = ticker["quotes"]
            bid = _positive(quotes.get("best_bid"))
            ask = _positive(quotes.get("best_ask"))
        except (KeyError, TypeError, ValueError) as exc:
            raise PreflightError("Malformed or stale quote") from exc
        if age > 30 or bid <= 0 or ask <= bid:
            raise PreflightError("Quote is stale, crossed or untradeable")

    wallet = exchange.wallet_balances()
    balances = wallet.get("balances")
    if not isinstance(balances, list) or not balances:
        raise PreflightError("No authenticated demo wallet balances")
    if wallet.get("meta", {}).get("net_equity") is not None:
        if _positive(wallet["meta"]["net_equity"]) <= 0:
            raise PreflightError("Demo account has no equity")
    spendable = []
    for item in balances:
        if not isinstance(item, dict) or not isinstance(item.get("asset_symbol"), str):
            raise PreflightError("Malformed demo wallet")
        if _positive(item.get("available_balance")) > 0:
            spendable.append(item["asset_symbol"])
    if not spendable:
        raise PreflightError("No available demo funds")
    return PreflightReport(
        checked_at=instant.isoformat(),
        quoted_legs=len(to_quote),
        spendable_demo_assets=tuple(spendable),
        broker_margin_verified=False,
    )
