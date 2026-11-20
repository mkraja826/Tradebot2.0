"""Fail-closed signed account-wide flatness gate for manual Demo FIRE.

The global margined positions endpoint can lag a new fill. For that reason
both FIRE products are independently queried through filtered real-time
positions, and ALL open orders are checked through the base Delta client.
No AI or broker mutation takes place here.
"""
from decimal import Decimal, InvalidOperation

from tradebot.delta import DEMO_API, DeltaDemo

FIRE_SYMBOLS = ("BTCUSD", "XAUTUSD")


class AccountExposureRejected(ValueError):
    """Current demo account evidence cannot authorize another entry."""


def _amount(value):
    if isinstance(value, bool):
        raise AccountExposureRejected("Invalid signed position quantity")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise ValueError
        return amount
    except (ValueError, TypeError, InvalidOperation):
        raise AccountExposureRejected("Invalid signed position quantity") from None


def require_flat_demo_account(exchange, *, selected_symbol=None, selected_product_id=None):
    """Prove no current account position or order before changing leverage/FIRE.

    Require unfiltered account-wide margin positions and filtered real-time
    positions for BTC and Gold. A zero snapshot is never a deployment permit:
    the caller must still enforce durable reservations and risk limits.
    """
    if getattr(exchange, "base_url", None) != DEMO_API:
        raise AccountExposureRejected("Only Delta India DEMO is permitted")
    if selected_symbol is not None and selected_symbol not in FIRE_SYMBOLS:
        raise AccountExposureRejected("Unsupported FIRE instrument")
    profile = exchange._request("GET", "/v2/profile", auth=True)["result"]
    if not isinstance(profile, dict) or profile.get("margin_mode") != "isolated":
        raise AccountExposureRejected("Broker isolated-margin mode not verified")

    global_positions = exchange._request(
        "GET", "/v2/positions/margined", auth=True
    )["result"]
    if not isinstance(global_positions, list):
        raise AccountExposureRejected("Account-wide positions unverified")
    for row in global_positions:
        if (not isinstance(row, dict)
                or not str(row.get("product_id", "")).isdigit()):
            raise AccountExposureRejected("Unidentified account position")
        if _amount(row.get("size")) != 0:
            raise AccountExposureRejected("Account has open exposure")

    # Deliberately call the unfiltered base method, not FireMarket.open_orders
    # (which hides other products). Pagination failures must block entries.
    orders = DeltaDemo.open_orders(exchange)
    if not isinstance(orders, list):
        raise AccountExposureRejected("Account orders not verified")
    for row in orders:
        if (not isinstance(row, dict) or not row.get("id") or
                not str(row.get("product_id", "")).isdigit()):
            raise AccountExposureRejected("Unidentified account pending order")
    if orders:
        raise AccountExposureRejected("Account has pending orders")

    ids = {}
    for symbol in FIRE_SYMBOLS:
        product = exchange._request("GET", "/v2/products/" + symbol)["result"]
        if (not isinstance(product, dict) or product.get("symbol") != symbol
                or product.get("contract_type") != "perpetual_futures"
                or type(product.get("id")) is not int or product["id"] <= 0):
            raise AccountExposureRejected("FIRE product not verified")
        ids[symbol] = product["id"]
        live = exchange._request(
            "GET", "/v2/positions",
            params={"product_id": product["id"]}, auth=True
        )["result"]
        if isinstance(live, dict):
            live = [live]
        if not isinstance(live, list):
            raise AccountExposureRejected("Real-time market positions unverified")
        for row in live:
            if (not isinstance(row, dict)
                    or str(row.get("product_id", product["id"])) != str(product["id"])):
                raise AccountExposureRejected("Mismatched real-time product")
            if _amount(row.get("size")) != 0:
                raise AccountExposureRejected("FIRE market has open exposure")
    if selected_symbol is not None and ids[selected_symbol] != selected_product_id:
        raise AccountExposureRejected("Snapshot product ID changed")
    return {"account_flat_verified": True,
            "checked_markets": list(FIRE_SYMBOLS),
            "open_positions": 0, "open_orders": 0}
