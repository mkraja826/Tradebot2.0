"""Size a new flat-market FIRE entry from Delta's USD margin and product data."""
from decimal import Decimal


MARGIN_SHARE = Decimal("0.20")
MAX_BROKER_LEVERAGE = Decimal("20")
MAX_EFFECTIVE_LEVERAGE = Decimal("20")


def number(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid Delta sizing input")
    return result


def entry_budget(exchange, symbol, product_id, price, *, planned_leverage=None):
    product = exchange._request("GET", "/v2/products/" + symbol)["result"]
    if (product["symbol"] != symbol or product["id"] != product_id
            or product["contract_type"] != "perpetual_futures"
            or product["settling_asset"]["symbol"] != "USD"
            or product["notional_type"] != "vanilla"):
        raise ValueError("Unexpected FIRE contract specification")
    settings = exchange._request("GET", f"/v2/products/{product_id}/orders/leverage", auth=True)["result"]
    if str(settings.get("product_id", product_id)) != str(product_id):
        raise ValueError("Unexpected leverage product")
    broker_leverage = number(settings["leverage"])
    if not 0 < broker_leverage <= MAX_BROKER_LEVERAGE:
        raise ValueError("Configured broker leverage exceeds demo safety policy")
    leverage = (broker_leverage if planned_leverage is None else number(planned_leverage))
    if not 0 < leverage <= MAX_BROKER_LEVERAGE or leverage != leverage.to_integral_value():
        raise ValueError("Planned leverage exceeds 20x policy")
    wallet = exchange.wallet_balances()
    equity = number(wallet["meta"]["net_equity"])
    usd, = (r for r in wallet["balances"] if r["asset_symbol"] == "USD")
    available = number(usd["available_balance"])
    ceiling = equity * MARGIN_SHARE
    multiplier = number(product["contract_value"])
    per_contract = multiplier * number(price)
    if not per_contract or not leverage:
        raise ValueError("Invalid contract multiplier, price or leverage")
    base_rate = number(product["initial_margin"]) / 100
    selected_rate = 1 / leverage
    fee = number(product["taker_commission_rate"])
    scaling = number(product.get("initial_margin_scaling_factor") or 0) / 100
    threshold = number(product["max_leverage_notional"]) if scaling else 0

    def margin(quantity):
        exposure = per_contract * quantity
        rate = max(selected_rate, base_rate + scaling * max(0, exposure - threshold))
        return exposure * rate

    high = int(min(ceiling, available) / (per_contract * max(base_rate, selected_rate)))
    if product.get("position_size_limit"):
        high = min(high, int(number(product["position_size_limit"])))
    if product.get("position_notional_limit"):
        high = min(high, int(number(product["position_notional_limit"]) / per_contract))
    high = min(high, int(equity * MAX_EFFECTIVE_LEVERAGE / per_contract))
    # One-contract supervised FIRE pilot; backend hard limit, not just UI.
    high = min(high, 1)
    low = 0
    while low < high:
        mid = (low + high + 1) // 2
        required = margin(mid)
        if required <= ceiling and required + 2 * fee * per_contract * mid <= available:
            low = mid
        else:
            high = mid - 1
    return {"margin_budget_usd": str(ceiling), "leverage": str(leverage),
            "equity_usd": str(equity), "taker_commission_rate": str(fee),
            "risk_policy": "fire-demo-risk-v2-dynamic-leverage",
            "broker_leverage": str(broker_leverage),
            "contract_value": str(multiplier), "max_contracts_per_entry": low,
            "notional_per_contract_usd": str(per_contract), "max_margin_usd": str(margin(low))}
