"""Read-only, operator-visible Delta DEMO Gold commissioning readiness gate.

No order placement, leverage modification, database writes, or AI calls.
Passing this gate does NOT authorize a trade: a separate supervised, durable
FIRE-linked execution and independent human approval are still mandatory.
"""
import argparse
import json
import os
import subprocess
from decimal import Decimal, InvalidOperation
from urllib.request import urlopen

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_release_gate import verify_staging_samples


def _services_active():
    return all(
        subprocess.run(
            ["systemctl", "is-active", "--quiet", name], check=False
        ).returncode == 0
        for name in ("tradebot2-dashboard", "tradebot2-fire-watchdog")
    )


def _fire_disabled():
    for endpoint in ("/api/fire", "/api/fire/XAUTUSD"):
        with urlopen("http://127.0.0.1:8765" + endpoint, timeout=5) as response:
            body = json.load(response)
        if not isinstance(body, dict) or body.get("execution_enabled") is not False:
            return False
    return True


def commissioning_preflight(
    exchange, data_dir, *, pause=None,
    check_services=_services_active,
    check_fire=_fire_disabled,
):
    """Fail shut if any signed exchange or local process evidence is missing.

    check_services/check_fire are injectable for offline unit tests only.
    All broker access is through a client that prohibits mutations.
    """
    blockers = []
    report = {
        "environment": "delta-india-demo",
        "mode": "read_only",
        "order_mutations": False,
        "ai_calls": 0,
        "trade_authorized": False,
        "ready_for_supervised_operator_review": False,
        "gold_tick_size": None,
        "gold_leverage": None,
        "broker_flat_two_samples": False,
        "watchdog_and_dashboard_active": False,
        "both_fire_endpoints_disabled": False,
        "broker_liquidation_price_verified": False,
        "blockers": blockers,
    }
    if getattr(exchange, "base_url", None) != DEMO_API or exchange.allow_orders is not False:
        blockers.append("read_only_delta_demo_client_required")
        return report

    try:
        gate = verify_staging_samples(
            exchange, data_dir, **({"pause": pause} if pause is not None else {})
        )
        report["broker_flat_two_samples"] = bool(
            gate.get("broker_flat_two_samples") is True
            and gate.get("samples_checked") == 2
            and gate.get("positions") == 0
            and gate.get("open_orders") == 0
            and gate.get("unresolved_fire_receipts") == 0
            and gate.get("account_margin_mode") == "isolated"
            and gate.get("blockers") == []
        )
        if not report["broker_flat_two_samples"]:
            blockers.append("account_wide_broker_release_gate_not_passed")
    except Exception:
        blockers.append("account_wide_broker_evidence_unavailable")

    try:
        report["watchdog_and_dashboard_active"] = check_services() is True
        if not report["watchdog_and_dashboard_active"]:
            blockers.append("dashboard_or_watchdog_not_active")
    except Exception:
        blockers.append("dashboard_or_watchdog_status_unavailable")

    try:
        report["both_fire_endpoints_disabled"] = check_fire() is True
        if not report["both_fire_endpoints_disabled"]:
            blockers.append("fire_execution_not_disabled")
    except Exception:
        blockers.append("fire_execution_status_unavailable")

    try:
        product = exchange._request("GET", "/v2/products/XAUTUSD")["result"]
        ticker = exchange.ticker("XAUTUSD")
        assert isinstance(product, dict) and isinstance(ticker, dict)
        assert product.get("symbol") == ticker.get("symbol") == "XAUTUSD"
        assert product.get("contract_type") == "perpetual_futures"
        product_id = product.get("id")
        assert type(product_id) is int and product_id > 0
        assert product_id == ticker.get("product_id")
        tick = Decimal(str(product.get("tick_size")))
        tick_ticker = Decimal(str(ticker.get("tick_size")))
        assert tick.is_finite() and tick > 0 and tick == tick_ticker
        leverage_result = exchange._request(
            "GET", f"/v2/products/{product_id}/orders/leverage", auth=True
        )["result"]
        assert isinstance(leverage_result, dict)
        assert str(leverage_result.get("product_id")) == str(product_id)
        lev = Decimal(str(leverage_result.get("leverage")))
        assert lev.is_finite() and lev == lev.to_integral_value() and 1 <= lev <= 20
        report["gold_tick_size"] = str(tick)
        report["gold_leverage"] = int(lev)
    except Exception:
        # Never leak exchange response content or credentials into public logs.
        blockers.append("gold_product_or_leverage_not_verified")

    report["ready_for_supervised_operator_review"] = not blockers
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data")
    )
    args = parser.parse_args(argv)
    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    report = commissioning_preflight(exchange, args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["ready_for_supervised_operator_review"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
