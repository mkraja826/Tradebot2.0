"""Read-only Delta DEMO account-exposure observations cross-checked with FIRE receipts.

Two authenticated GET sweeps separated by at least 11 elapsed seconds.
This is an operator diagnostic ONLY: never authority to open a trade, restart
a service, clear an emergency lock or claim complete historical broker fills.
The Delta margined endpoint can lag; filtered real-time BTC/Gold positions
are inspected independently. A zero snapshot does not prove ongoing flatness.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_inventory import read_inventory, InventoryEvidenceError

SYMBOLS = ("BTCUSD", "XAUTUSD")
SAMPLE_INTERVAL_SECONDS = 11
MAX_SWEEP_SECONDS = 90
MAX_PAGES = 100


class BrokerInventoryError(ValueError):
    """Sanitized evidence-failure code, never provider response content."""


def _quantity(raw):
    if type(raw) not in (str, int, Decimal):
        raise BrokerInventoryError("invalid_position_size")
    try:
        value = Decimal(str(raw))
    except (ValueError, TypeError, InvalidOperation):
        raise BrokerInventoryError("invalid_position_size") from None
    if not value.is_finite() or value != value.to_integral_value():
        raise BrokerInventoryError("invalid_position_size")
    return value


def _product_id(raw):
    if type(raw) is int and raw > 0:
        return raw
    if type(raw) is str and raw.isdecimal() and int(raw) > 0:
        return int(raw)
    raise BrokerInventoryError("unidentified_broker_product")


def _order_id(raw):
    if type(raw) not in (str, int) or not str(raw).strip():
        raise BrokerInventoryError("unidentified_open_order")
    return str(raw)


def _get(exchange, path, *, params=None):
    reply = exchange._request("GET", path, params=params, auth=True)
    if not isinstance(reply, dict):
        raise BrokerInventoryError("invalid_authenticated_response")
    return reply


def _all_open_orders(exchange):
    """Inspect every account order page. Missing pagination metadata fails shut."""
    orders, cursor, seen = {}, None, set()
    for _ in range(MAX_PAGES):
        params = {"states": "open,pending", "page_size": 50}
        if cursor is not None:
            params["after"] = cursor
        result = _get(exchange, "/v2/orders", params=params)
        rows, meta = result.get("result"), result.get("meta")
        if (not isinstance(rows, list) or len(rows) > 50
                or any(not isinstance(v, dict) for v in rows)
                or not isinstance(meta, dict) or "after" not in meta):
            raise BrokerInventoryError("open_orders_pagination_unverified")
        for row in rows:
            oid = _order_id(row.get("id"))
            _product_id(row.get("product_id"))
            if oid in orders and orders[oid] != row:
                raise BrokerInventoryError("conflicting_broker_order_identity")
            orders[oid] = row
        nxt = meta["after"]
        if nxt in (None, ""):
            return len(orders)
        if not isinstance(nxt, str) or nxt in seen or nxt == cursor:
            raise BrokerInventoryError("open_orders_pagination_unverified")
        seen.add(nxt)
        cursor = nxt
    raise BrokerInventoryError("open_orders_pagination_unverified")


def _positions_for_product(exchange, pid):
    rows = _get(exchange, "/v2/positions", params={"product_id": pid}).get("result")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise BrokerInventoryError("realtime_position_unverified")
    values = []
    for row in rows:
        if not isinstance(row, dict) or _product_id(row.get("product_id", pid)) != pid:
            raise BrokerInventoryError("realtime_position_unverified")
        values.append(_quantity(row.get("size")))
    if sum(v != 0 for v in values) > 1:
        raise BrokerInventoryError("multiple_realtime_positions")
    return str(sum(values, Decimal(0)))


def _sample(exchange):
    """Authenticated unfiltered margin, full open orders and two real-time markets."""
    profile = _get(exchange, "/v2/profile").get("result")
    if not isinstance(profile, dict):
        raise BrokerInventoryError("account_profile_unverified")
    isolated = profile.get("margin_mode") == "isolated"

    wide = _get(exchange, "/v2/positions/margined")
    rows = wide.get("result")
    if not isinstance(rows, list):
        raise BrokerInventoryError("account_positions_unverified")
    # A broker-supplied pagination cursor cannot be ignored.
    meta = wide.get("meta")
    if meta is not None and (
            not isinstance(meta, dict) or meta.get("after") not in (None, "")):
        raise BrokerInventoryError("account_positions_pagination_unverified")
    active = []
    by_product = Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise BrokerInventoryError("account_positions_unverified")
        pid = _product_id(row.get("product_id"))
        size = _quantity(row.get("size"))
        if size:
            active.append(pid)
            by_product[pid] += 1
    if any(count > 1 for count in by_product.values()):
        raise BrokerInventoryError("multiple_margined_positions")

    open_orders = _all_open_orders(exchange)
    realtime = {}
    product_ids = {}
    for symbol in SYMBOLS:
        product = _get(exchange, "/v2/products/" + symbol).get("result")
        if (not isinstance(product, dict) or product.get("symbol") != symbol
                or product.get("contract_type") != "perpetual_futures"):
            raise BrokerInventoryError("fire_product_unverified")
        pid = _product_id(product.get("id"))
        if pid in product_ids.values():
            raise BrokerInventoryError("fire_product_identity_conflict")
        product_ids[symbol] = pid
        realtime[symbol] = _positions_for_product(exchange, pid)
    return {
        "isolated_margin_observed": isolated,
        "account_margined_nonzero_positions": len(active),
        "account_open_orders": open_orders,
        "realtime_fire_sizes": realtime,
        "fire_product_ids": product_ids,
        # Do not expose raw account/order IDs or individual balances in output.
        "margined_fire_consistency": all(
            (product_ids[symbol] in active) == (Decimal(size) != 0)
            for symbol, size in realtime.items()),
    }


def observe_broker_inventory(exchange, data_dir, *, pause=time.sleep,
                             monotonic=time.monotonic):
    """Return a bounded diagnostic. Failures are safely attributed and never green."""
    report = {
        "environment": "delta-india-demo", "mode": "read_only",
        "trade_authorized": False, "safe_to_enable_fire": False,
        "is_account_flatness_verified_for_future_orders": False,
        "is_complete_broker_trade_history": False,
        "is_account_realized_pnl": False, "ai_calls": 0, "order_mutations": False,
        "samples_checked": 0, "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "sample_interval_verified": False,
        "broker_positions_last": None, "broker_open_orders_last": None,
        "realtime_fire_sizes_last": None, "local_evidence_status": "unavailable",
        "observation_status": "blocked_or_unverified", "blockers": [],
    }
    blockers = report["blockers"]
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(
            exchange, "allow_orders", None) is not False:
        blockers.append("read_only_delta_demo_client_required")
        return report
    if not callable(pause) or not callable(monotonic):
        blockers.append("invalid_observation_clock")
        return report
    try:
        original = read_inventory(data_dir, limit=0)
        report["local_evidence_status"] = original["evidence_status"]
        report["local_receipts_total"] = original["total_local_receipts"]
        report["local_requires_broker_review_count"] = original["requires_broker_review_count"]
        if original["evidence_status"] != "inventory_complete_for_local_coverage_only":
            blockers.append("local_history_incomplete_or_ambiguous")
    except (InventoryEvidenceError, OSError, ValueError):
        blockers.append("local_history_unavailable")
        return report

    snapshots = []
    for index in range(2):
        try:
            if index:
                pause(SAMPLE_INTERVAL_SECONDS)
                delay = monotonic() - previous_end
                if (not isinstance(delay, (int, float)) or
                        not math.isfinite(delay) or delay < SAMPLE_INTERVAL_SECONDS):
                    blockers.append("sample_spacing_not_verified")
                    break
                report["sample_interval_verified"] = True
            started = monotonic()
            if not isinstance(started, (int, float)) or not math.isfinite(started):
                raise BrokerInventoryError("observation_clock_unverified")
            item = _sample(exchange)
            elapsed = monotonic() - started
            if (not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed)
                    or elapsed < 0 or elapsed > MAX_SWEEP_SECONDS):
                raise BrokerInventoryError("broker_sample_timing_unverified")
            snapshots.append(item)
            report["samples_checked"] += 1
            previous_end = monotonic()
        except BrokerInventoryError as exc:
            blockers.append(exc.args[0])
            break
        except Exception:
            blockers.append("authenticated_broker_read_unavailable")
            break

    if snapshots:
        last = snapshots[-1]
        report["broker_positions_last"] = last["account_margined_nonzero_positions"]
        report["broker_open_orders_last"] = last["account_open_orders"]
        report["realtime_fire_sizes_last"] = last["realtime_fire_sizes"]
    if len(snapshots) == 2:
        if snapshots[0]["fire_product_ids"] != snapshots[1]["fire_product_ids"]:
            blockers.append("fire_product_changed_between_samples")
        for item in snapshots:
            if not item["isolated_margin_observed"]:
                blockers.append("account_isolated_margin_unverified")
            if item["account_margined_nonzero_positions"]:
                blockers.append("account_has_exposure")
            if item["account_open_orders"]:
                blockers.append("account_has_open_orders")
            if any(Decimal(size) != 0 for size in item["realtime_fire_sizes"].values()):
                blockers.append("fire_market_has_exposure")
            if not item["margined_fire_consistency"]:
                blockers.append("lagging_or_inconsistent_broker_positions")
        if snapshots[0] != snapshots[1]:
            blockers.append("broker_inventory_changed_between_samples")
    else:
        blockers.append("two_broker_samples_unavailable")

    try:
        final = read_inventory(data_dir, limit=0)
        if final != original:
            blockers.append("local_evidence_changed_during_broker_observation")
    except (InventoryEvidenceError, OSError, ValueError):
        blockers.append("local_evidence_changed_or_unavailable")
    report["blockers"] = sorted(set(blockers))
    if not report["blockers"]:
        report["observation_status"] = "two_flat_snapshots_observed_not_trade_authority"
    report["as_of_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    args = parser.parse_args(argv)
    broker = DeltaDemo(api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
                       api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""), allow_orders=False)
    report = observe_broker_inventory(broker, args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["observation_status"] == "two_flat_snapshots_observed_not_trade_authority" else 2


if __name__ == "__main__":
    raise SystemExit(main())
