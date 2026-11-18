"""Turn a market snapshot into a bounded, diverse AI research universe.

The AI chooses its strategy; this module does not define or whitelist strategies.
The option limit is a context-size budget, not a financial risk limit.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from math import ceil


def _decimal(value, default=Decimal("Infinity")):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else default
    except (TypeError, ValueError, InvalidOperation):
        return default


def build_ai_context(snapshot: dict, *, max_options: int = 128) -> tuple[dict, list[dict]]:
    """Returns (fresh market context, allowed BTC derivative product catalog).

    Only products with a recent, non-crossed, exchange-quoted bid/ask price are
    presented to the model as executable candidates. Options are distributed
    across expiries and call/put types, then ranked by moneyness. Product
    selection itself is not an order authorization.
    """
    if not 8 <= max_options <= 512:
        raise ValueError("max_options must be between 8 and 512")
    core = snapshot["core"]
    futures = [q for q in snapshot.get("futures", []) if q.get("usable_quote")]
    options = [q for q in snapshot.get("options", []) if q.get("usable_quote")]
    reference = _decimal(core["ticker"].get("spot_price"))
    if not reference.is_finite() or reference <= 0:
        reference = (_decimal(core["best_bid"]) + _decimal(core["best_ask"])) / 2
    if not reference.is_finite() or reference <= 0:
        raise ValueError("BTC price reference unavailable")

    by_group = defaultdict(list)
    for quote in options:
        by_group[(str(quote.get("settlement_time") or "unknown"),
                  quote["contract_type"])].append(quote)
    for quotes in by_group.values():
        quotes.sort(key=lambda q: (
            abs(_decimal(q.get("strike_price")) - reference)
            if _decimal(q.get("strike_price")).is_finite()
            else Decimal("Infinity"),
            str(q.get("symbol") or ""),
        ))

    selected = []
    keys = sorted(by_group)
    # Round-robin across option expiries and calls/puts so rare expiries and
    # wings remain candidates, rather than only near-money nearest expiry.
    while len(selected) < max_options and keys:
        for key in list(keys):
            group = by_group[key]
            if group:
                selected.append(group.pop(0))
                if len(selected) >= max_options:
                    break
            if not group:
                keys.remove(key)
    candidates = futures + selected
    products = [{
        "id": q["product_id"], "symbol": q["symbol"],
        "contract_type": q["contract_type"], "state": "live",
        "strike_price": q.get("strike_price"),
        "settlement_time": q.get("settlement_time"),
        "contract_value": q.get("contract_value"),
    } for q in candidates]
    if not products:
        raise ValueError("No fresh quoted BTC derivatives available")
    context = {
        "environment": snapshot["environment"],
        "session_phase": snapshot["session_phase"],
        "collected_at": snapshot["collected_at"],
        "core": core,
        "technical": snapshot["technical"],
        "futures": futures,
        "options": selected,
        "demo_funds": snapshot.get("demo_funds"),
        "coverage": {
            "quoted_futures": len(futures),
            "usable_option_quotes_total": len(options),
            "sampled_option_quotes": len(selected),
            "candidate_selection": "balanced across expiry and call/put; near-money first",
            "not_a_margin_approval": True,
        },
    }
    return context, products
