"""Fail-closed demo leverage synchronization and post-fill liquidation evidence.

Changing leverage is a broker mutation, never a strategy shortcut. The
user-controlled 20x maximum is a CEILING; a risk gate still sizes every entry.
"""
from decimal import Decimal, InvalidOperation

from tradebot.fire_market import positions_for_fire


class LeverageRejected(ValueError):
    pass


def _positive(raw):
    try:
        value = Decimal(str(raw))
        if not value.is_finite() or value <= 0:
            raise ValueError
        return value
    except (TypeError, ValueError, InvalidOperation):
        raise LeverageRejected("Invalid broker leverage or liquidation evidence") from None


def _leverage_setting(exchange, product_id):
    result = exchange._request(
        "GET", f"/v2/products/{product_id}/orders/leverage", auth=True
    )["result"]
    if not isinstance(result, dict) or str(result.get("product_id", product_id)) != str(product_id):
        raise LeverageRejected("Broker leverage product mismatch")
    return _positive(result.get("leverage"))


def synchronize_leverage(exchange, product_id, leverage):
    """Never change leverage with any selected-product position/order.

    A failed or ambiguous POST must never be retried automatically. The
    subsequent entry is refused until a signed GET confirms the setting.
    """
    if type(leverage) is not int or not 1 <= leverage <= 20:
        raise LeverageRejected("Selected leverage exceeds 20x")
    current = _leverage_setting(exchange, product_id)
    if current > 20:
        raise LeverageRejected("Operator must reduce legacy broker leverage first")
    if current != leverage:
        rows = positions_for_fire(exchange)
        if (not isinstance(rows, list)
                or any(not isinstance(row, dict) or
                       _positive_or_zero(row.get("size")) != 0 for row in rows)
                or exchange.open_orders()):
            raise LeverageRejected("Leverage change requires flat broker account for selected market")
        reply = exchange._request(
            "POST", f"/v2/products/{product_id}/orders/leverage",
            auth=True, payload={"leverage": str(leverage)}
        )["result"]
        if not isinstance(reply, dict) or str(reply.get("product_id")) != str(product_id) or _positive(reply.get("leverage")) != leverage:
            raise LeverageRejected("Broker leverage mutation not acknowledged")
    if _leverage_setting(exchange, product_id) != leverage:
        raise LeverageRejected("Broker leverage readback mismatch")
    return leverage


def _positive_or_zero(raw):
    try:
        value = Decimal(str(raw))
        if not value.is_finite():
            raise ValueError
        return value
    except (TypeError, ValueError, InvalidOperation):
        raise LeverageRejected("Unverified position size") from None


def verify_liquidation_clearance(exchange, product_id, plan, position):
    """Only signed margin-aware broker position evidence can verify clearance.

    /v2/positions (real-time) does not include liquidation_price. The
    /v2/positions/margined snapshot may lag fills; missing evidence fails shut.
    Require isolated margin and >=1% entry-price buffer beyond SL.
    """
    if not isinstance(position, dict):
        raise LeverageRejected("Missing real-time filled position")
    entry = _positive(position.get("entry_price"))
    expected = plan["contracts"] if plan["direction"] == "LONG" else -plan["contracts"]
    if _positive_or_zero(position.get("size")) != expected:
        raise LeverageRejected("Position size changed before liquidation check")
    rows = exchange._request(
        "GET", "/v2/positions/margined",
        params={"product_ids": str(product_id)}, auth=True
    )["result"]
    if not isinstance(rows, list):
        raise LeverageRejected("Invalid margin-aware position list")
    matches = [row for row in rows if isinstance(row, dict) and
               str(row.get("product_id")) == str(product_id) and
               _positive_or_zero(row.get("size")) != 0]
    if len(matches) != 1 or matches[0].get("margin_mode") != "isolated":
        raise LeverageRejected("Isolated margin position not verified")
    broker_position = matches[0]
    if _positive_or_zero(broker_position.get("size")) != expected:
        raise LeverageRejected("Margined position size mismatch")
    # The analytical endpoint can lag by up to 10 seconds. A same-sized
    # *previous* position must not certify the newly filled entry.
    margin_entry = _positive(broker_position.get("entry_price"))
    if abs(margin_entry - entry) > entry * Decimal("0.0001"):
        raise LeverageRejected("Margined entry price differs from live fill")
    liquidation = _positive(broker_position.get("liquidation_price"))
    stop = _positive(plan["stop_loss"])
    gap = entry * Decimal("0.01")
    if plan["direction"] == "LONG" and not liquidation + gap < stop:
        raise LeverageRejected("Liquidation too close to LONG stop-loss")
    if plan["direction"] == "SHORT" and not liquidation - gap > stop:
        raise LeverageRejected("Liquidation too close to SHORT stop-loss")
    return {"liquidation_verified": True, "liquidation_price": str(liquidation)}
