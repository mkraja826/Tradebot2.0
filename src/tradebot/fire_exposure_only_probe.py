"""Read-only Delta India DEMO exposure sample independent of margin-mode proof.

A successful /v2/sub_accounts GET may return an empty list for the API key.
That cannot establish isolated margin, but must not prevent separate,
sanitized account-wide position/order observation. This diagnostic has
NO authority to trade, deploy, restart, or assert two-sweep flatness.
"""
import json
import os
from decimal import Decimal

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_broker_inventory import (
    _get, _all_open_orders, _positions_for_product, _product_id, _quantity,
)

MARKETS = ("BTCUSD", "XAUTUSD")
MAX_POSITION_ROWS = 10_000


def observe_exposure_without_margin(exchange):
    """One signed GET-only, unfiltered account snapshot; fail closed."""
    result = {
        "environment": "delta-india-demo", "mode": "read_only",
        "status": "blocked", "blocker": "not_checked",
        "stage": "client",
        "account_wide_margined_positions_nonzero": None,
        "account_wide_open_or_pending_orders": None,
        "realtime_fire_position_sizes": None,
        "margined_realtime_consistent": False,
        "any_exposure_observed": None,
        "margin_mode_verified": False,
        "two_sweep_flatness_verified": False,
        "full_financial_reconciliation_verified": False,
        "safe_to_deploy": False, "safe_to_enable_fire": False,
        "trade_authorized": False, "broker_order_mutations": False,
        "service_mutations": False, "ai_calls": 0,
    }
    if (not isinstance(exchange, DeltaDemo)
            or getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        result["blocker"] = "read_only_delta_demo_client_required"
        return result

    try:
        result["stage"] = "account_margined_positions"
        reply = _get(exchange, "/v2/positions/margined")
        rows = reply.get("result")
        if not isinstance(rows, list) or len(rows) > MAX_POSITION_ROWS:
            raise ValueError("unbounded positions")
        meta = reply.get("meta")
        if (meta is not None and
                (not isinstance(meta, dict)
                 or meta.get("after") not in (None, ""))):
            raise ValueError("uninspected positions page")
        nonzero = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid position")
            pid = _product_id(row.get("product_id"))
            size = _quantity(row.get("size"))
            if size:
                if pid in nonzero:
                    raise ValueError("duplicate active position identity")
                nonzero[pid] = size
        result["account_wide_margined_positions_nonzero"] = len(nonzero)

        result["stage"] = "account_orders_all_pages"
        orders = _all_open_orders(exchange)
        result["account_wide_open_or_pending_orders"] = orders

        product_ids = {}
        observed = {}
        for symbol in MARKETS:
            result["stage"] = "realtime_" + symbol.lower()
            product = _get(exchange, "/v2/products/" + symbol).get("result")
            if (not isinstance(product, dict)
                    or product.get("symbol") != symbol
                    or product.get("contract_type") != "perpetual_futures"):
                raise ValueError("invalid product identity")
            pid = _product_id(product.get("id"))
            if pid in product_ids.values():
                raise ValueError("duplicate product identity")
            product_ids[symbol] = pid
            observed[symbol] = _positions_for_product(exchange, pid)

        result["realtime_fire_position_sizes"] = observed
        result["margined_realtime_consistent"] = all(
            nonzero.get(pid, Decimal(0)) == Decimal(observed[symbol])
            for symbol, pid in product_ids.items()
        )
        # A positional/order count is an exposure observation, NOT a claim
        # about account-wide flatness, account margin mode, or future risk.
        result["any_exposure_observed"] = bool(
            nonzero or orders or any(Decimal(v) for v in observed.values())
        )
        result["status"] = "signed_exposure_snapshot_observed"
        result["blocker"] = ("exposure_present" if result["any_exposure_observed"]
                              else "none_in_this_single_snapshot")
        if not result["margined_realtime_consistent"]:
            result["blocker"] = "margined_realtime_position_disagreement"
        result["stage"] = "complete"
    except Exception:
        # An upstream failure or unexpected schema must never expose broker
        # response contents or leave partially observed counts looking final.
        result.update(
            status="blocked",
            blocker="signed_broker_exposure_evidence_unavailable",
            account_wide_margined_positions_nonzero=None,
            account_wide_open_or_pending_orders=None,
            realtime_fire_position_sizes=None,
            margined_realtime_consistent=False,
            any_exposure_observed=None,
        )
    return result


def main():
    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    report = observe_exposure_without_margin(exchange)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    print("TRADING_ENABLED: false")
    return 0 if report["status"] == "signed_exposure_snapshot_observed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
