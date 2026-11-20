"""Read-only broker compatibility probe for supervised GPT-6 leverage rollout.

This is NOT a deployment authorization or a trade-safety certification.
It never calls paid AI, changes leverage, or places/cancels orders.
"""
import argparse
from decimal import Decimal, InvalidOperation
import json
import os

from tradebot.delta import DEMO_API
from tradebot.fire_market import FireMarket


SYMBOLS = ("BTCUSD", "XAUTUSD")


def _number(raw):
    try:
        if type(raw) is bool:
            raise ValueError
        value = Decimal(str(raw))
        if not value.is_finite():
            raise ValueError
        return value
    except (TypeError, InvalidOperation, ValueError):
        raise ValueError("invalid broker numeric evidence") from None


def audit_leverage_broker(markets):
    """Fail closed on missing signed evidence; report only known risk fields."""
    result = {
        "mode": "read_only",
        "environment": "delta-india-demo",
        "order_mutations": False,
        "ai_calls": 0,
        "safe_to_deploy": False,
        "markets": {},
        "blockers": [],
    }
    if set(markets) != set(SYMBOLS):
        return {**result, "blockers": ["both_fire_markets_required"]}
    for symbol in SYMBOLS:
        state = {"symbol": symbol, "configured_leverage": None,
                 "position_contracts": None, "open_orders": None,
                 "margin_mode": None, "liquidation_price": None,
                 "margin_evidence_verified": False}
        result["markets"][symbol] = state
        market = markets[symbol]
        if (getattr(market, "base_url", None) != DEMO_API
                or getattr(market, "allow_orders", None) is not False
                or getattr(market, "symbol", None) != symbol):
            result["blockers"].append(symbol.lower() + "_read_only_demo_required")
            continue
        try:
            pid = market.product_id
            if type(pid) is not int or pid <= 0:
                raise ValueError("invalid product ID")
            setting = market._request(
                "GET", f"/v2/products/{pid}/orders/leverage", auth=True
            )["result"]
            if (not isinstance(setting, dict)
                    or str(setting.get("product_id", pid)) != str(pid)):
                raise ValueError("invalid leverage product")
            leverage = _number(setting.get("leverage"))
            if leverage <= 0:
                raise ValueError("invalid leverage")
            state["configured_leverage"] = str(leverage)
            if leverage > 20:
                result["blockers"].append(symbol.lower() + "_leverage_above_20x")
            positions = market.positions()
            if not isinstance(positions, list) or any(
                    not isinstance(r, dict) or str(r.get("product_id")) != str(pid)
                    for r in positions):
                raise ValueError("invalid position list")
            sizes = [_number(r.get("size")) for r in positions]
            if any(v != v.to_integral_value() for v in sizes):
                raise ValueError("fractional contract position")
            if sum(1 for v in sizes if v) > 1:
                raise ValueError("multiple selected-product positions")
            total = sum(sizes)
            state["position_contracts"] = int(total)
            orders = market.open_orders()
            if not isinstance(orders, list) or any(
                    not isinstance(row, dict)
                    or str(row.get("product_id")) != str(pid)
                    or not row.get("id") for row in orders):
                raise ValueError("invalid pending orders")
            state["open_orders"] = len(orders)
            if total or orders:
                result["blockers"].append(symbol.lower() + "_has_exposure")
            if total:
                live = next(r for r in positions if _number(r.get("size")) != 0)
                live_entry = _number(live.get("entry_price"))
                reply = market._request(
                    "GET", "/v2/positions/margined",
                    params={"product_ids": str(pid)}, auth=True
                )["result"]
                if not isinstance(reply, list):
                    raise ValueError("invalid margin position list")
                matched = [r for r in reply if isinstance(r, dict)
                           and str(r.get("product_id")) == str(pid)
                           and _number(r.get("size")) != 0]
                if len(matched) != 1:
                    raise ValueError("margin position unavailable or stale")
                row = matched[0]
                if _number(row.get("size")) != total:
                    raise ValueError("margin size mismatch")
                margin_entry = _number(row.get("entry_price"))
                if live_entry <= 0 or abs(live_entry - margin_entry) > live_entry * Decimal("0.0001"):
                    raise ValueError("margin entry price mismatch")
                state["margin_mode"] = str(row.get("margin_mode"))
                liquidation = _number(row.get("liquidation_price"))
                if liquidation <= 0:
                    raise ValueError("unpriced liquidation")
                state["liquidation_price"] = str(liquidation)
                state["margin_evidence_verified"] = True
                if state["margin_mode"] != "isolated":
                    result["blockers"].append(symbol.lower() + "_isolated_margin_required")
        except Exception:
            # Never serialize upstream errors, response bodies, headers or keys.
            result["blockers"].append(symbol.lower() + "_broker_evidence_unverified")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    markets = {
        symbol: FireMarket(
            symbol, api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
            api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
            allow_orders=False,
        )
        for symbol in SYMBOLS
    }
    report = audit_leverage_broker(markets)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
