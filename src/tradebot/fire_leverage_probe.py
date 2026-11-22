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
from tradebot.fire_broker_inventory import _sample


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
        "account_wide": {
            "sampled": False,
            "isolated_margin_observed": False,
            "nonzero_margined_positions": None,
            "open_orders": None,
            "margined_fire_consistency": False,
            "single_sample_not_future_flatness": True,
        },
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "blockers": [],
    }
    if set(markets) != set(SYMBOLS):
        return {**result, "blockers": ["both_fire_markets_required"]}
    # Require both real read-only DEMO clients before performing any request.
    # A partially invalid market must not be used to waive the account read.
    for symbol in SYMBOLS:
        market = markets[symbol]
        if (getattr(market, "base_url", None) != DEMO_API
                or getattr(market, "allow_orders", None) is not False
                or getattr(market, "symbol", None) != symbol):
            result["blockers"].append(symbol.lower() + "_read_only_demo_required")
    if result["blockers"]:
        return result
    identities = {}
    for symbol in SYMBOLS:
        state = {"symbol": symbol, "configured_leverage": None,
                 "position_contracts": None, "open_orders": None,
                 "margin_mode": None, "liquidation_price": None,
                 "margin_evidence_verified": False}
        result["markets"][symbol] = state
        market = markets[symbol]
        try:
            pid = market.product_id
            if type(pid) is not int or pid <= 0 or pid in identities.values():
                raise ValueError("invalid or shared product ID")
            identities[symbol] = pid
            setting = market._request(
                "GET", f"/v2/products/{pid}/orders/leverage", auth=True
            )["result"]
            if (not isinstance(setting, dict)
                    or str(setting.get("product_id")) != str(pid)):
                raise ValueError("invalid or missing leverage product identity")
            leverage = _number(setting.get("leverage"))
            if leverage < 1 or leverage != leverage.to_integral_value():
                raise ValueError("invalid leverage")
            state["configured_leverage"] = str(leverage)
            # The profile is a separate signed request; the margined position
            # schema doesn't promise a margin_mode key.
            profile = market._request("GET", "/v2/profile", auth=True)["result"]
            if not isinstance(profile, dict) or profile.get("margin_mode") not in ("isolated", "portfolio"):
                raise ValueError("unknown account margin mode")
            state["margin_mode"] = profile["margin_mode"]
            if state["margin_mode"] != "isolated":
                result["blockers"].append(symbol.lower() + "_isolated_margin_required")
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
                if row.get("margin_mode", state["margin_mode"]) != state["margin_mode"]:
                    raise ValueError("position margin mode conflicts with profile")
                liquidation = _number(row.get("liquidation_price"))
                if liquidation <= 0:
                    raise ValueError("unpriced liquidation")
                state["liquidation_price"] = str(liquidation)
                state["margin_evidence_verified"] = True
                # Margin mode was checked on the signed profile even when
                # there were no active positions.
        except Exception:
            # Never serialize upstream errors, response bodies, headers or keys.
            result["blockers"].append(symbol.lower() + "_broker_evidence_unverified")

    # A filtered BTC/Gold view is never evidence that the whole account is
    # flat. Reuse the existing signed unfiltered margined-position, exhaustive
    # open-order pagination and real-time two-market reconciler. This extra
    # GET-only snapshot does NOT replace the independent 11-second two-sweep
    # local/broker account inventory in the final release review.
    if len(identities) == len(SYMBOLS):
        try:
            account = _sample(markets["BTCUSD"])
            if type(account) is not dict:
                raise ValueError("unverified account sample")
            if account.get("fire_product_ids") != identities:
                raise ValueError("broker product identity changed")
            wide = result["account_wide"]
            wide["sampled"] = True
            wide["isolated_margin_observed"] = (
                account.get("isolated_margin_observed") is True)
            positions = account.get("account_margined_nonzero_positions")
            orders = account.get("account_open_orders")
            if type(positions) is not int or positions < 0:
                raise ValueError("invalid unfiltered position count")
            if type(orders) is not int or orders < 0:
                raise ValueError("invalid unfiltered open order count")
            wide["nonzero_margined_positions"] = positions
            wide["open_orders"] = orders
            wide["margined_fire_consistency"] = (
                account.get("margined_fire_consistency") is True)
            if not wide["isolated_margin_observed"]:
                result["blockers"].append("account_isolated_margin_unverified")
            if positions:
                result["blockers"].append("account_has_margined_exposure")
            if orders:
                result["blockers"].append("account_has_open_orders")
            if not wide["margined_fire_consistency"]:
                result["blockers"].append("account_margined_realtime_positions_conflict")
            observed = account.get("realtime_fire_sizes")
            if (type(observed) is not dict
                    or set(observed) != set(SYMBOLS)):
                raise ValueError("unverified realtime markets")
            for symbol in SYMBOLS:
                selected = result["markets"][symbol]["position_contracts"]
                if (selected is not None
                        and _number(observed[symbol]) != selected):
                    result["blockers"].append(
                        symbol.lower() + "_exposure_changed_during_probe")
        except Exception:
            # Never serialize arbitrary private exchange bodies or errors.
            result["blockers"].append("account_wide_broker_evidence_unverified")
    else:
        result["blockers"].append("both_product_identifications_required")

    result["blockers"] = sorted(set(result["blockers"]))
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
