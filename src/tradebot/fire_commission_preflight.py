"""Read-only, operator-visible Delta DEMO Gold commissioning readiness gate.

No order placement, leverage modification, database writes, or AI calls.
Passing this gate does NOT authorize a trade: a separate supervised, durable
FIRE-linked execution and independent human approval are still mandatory.
"""
import argparse
import json
import os
import subprocess
from decimal import Decimal
from urllib.request import urlopen

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_release_gate import verify_staging_samples
from tradebot.commissioning_equity import signed_equity_readiness


def _services_active():
    return all(
        subprocess.run(
            ["systemctl", "is-active", "--quiet", name], check=False, timeout=3
        ).returncode == 0
        for name in ("tradebot2-dashboard", "tradebot2-fire-watchdog",
                     "tradebot2-equity-monitor")
    )


def _fire_disabled():
    for endpoint in ("/api/fire", "/api/fire/XAUTUSD"):
        with urlopen("http://127.0.0.1:8765" + endpoint, timeout=5) as response:
            body = json.load(response)
        if not isinstance(body, dict) or body.get("execution_enabled") is not False:
            return False
    return True


def commissioning_preflight(
    exchange, data_dir, *, pause=None, monotonic=None,
    check_services=_services_active,
    check_fire=_fire_disabled,
    check_equity=signed_equity_readiness,
):
    """Fail shut if any signed exchange or local process evidence is missing.

    check_services/check_fire/check_equity are injectable for offline tests only.
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
        "equity_prerequisites_verified": False,
        "equity_assessment": None,
        "blockers": blockers,
    }
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(exchange, "allow_orders", None) is not False:
        blockers.append("read_only_delta_demo_client_required")
        return report

    try:
        options = {}
        if pause is not None:
            options["pause"] = pause
        if monotonic is not None:
            options["monotonic"] = monotonic
        gate = verify_staging_samples(exchange, data_dir, **options)
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
        if (not isinstance(product, dict) or not isinstance(ticker, dict)
                or product.get("symbol") != "XAUTUSD" or ticker.get("symbol") != "XAUTUSD"
                or product.get("contract_type") != "perpetual_futures"):
            raise ValueError("Gold product identity not verified")
        product_id = product.get("id")
        if (type(product_id) is not int or product_id <= 0
                or type(ticker.get("product_id")) is not int or product_id != ticker["product_id"]):
            raise ValueError("Gold product identity mismatch")
        tick = Decimal(str(product.get("tick_size")))
        tick_ticker = Decimal(str(ticker.get("tick_size")))
        if not tick.is_finite() or tick <= 0 or tick != tick_ticker:
            raise ValueError("Gold tick size not verified")
        leverage_result = exchange._request(
            "GET", f"/v2/products/{product_id}/orders/leverage", auth=True
        )["result"]
        if not isinstance(leverage_result, dict) or str(leverage_result.get("product_id")) != str(product_id):
            raise ValueError("Gold leverage identity not verified")
        lev = Decimal(str(leverage_result.get("leverage")))
        if not lev.is_finite() or lev != lev.to_integral_value() or not 1 <= lev <= 20:
            raise ValueError("Gold leverage outside safety policy")
        report["gold_tick_size"] = str(tick)
        report["gold_leverage"] = int(lev)
    except Exception:
        # Never leak exchange response content or credentials into public logs.
        blockers.append("gold_product_or_leverage_not_verified")

    try:
        assessment = check_equity(exchange, data_dir)
        report["equity_assessment"] = assessment
        report["equity_prerequisites_verified"] = (
            isinstance(assessment, dict) and assessment.get("approved") is True
            and assessment.get("trade_authorized") is False)
        if not report["equity_prerequisites_verified"]:
            blockers.append("equity_risk_prerequisites_not_passed")
    except Exception:
        blockers.append("signed_equity_prerequisites_unavailable")

    # A service can stop, or an endpoint can become enabled, while signed
    # broker/equity reads are in progress. Recheck immediately before declaring
    # readiness; a previously healthy result must not authorize a stale gate.
    if report["watchdog_and_dashboard_active"]:
        try:
            if check_services() is not True:
                report["watchdog_and_dashboard_active"] = False
                blockers.append("service_health_changed_during_preflight")
        except Exception:
            report["watchdog_and_dashboard_active"] = False
            blockers.append("service_health_recheck_unavailable")
    if report["both_fire_endpoints_disabled"]:
        try:
            if check_fire() is not True:
                report["both_fire_endpoints_disabled"] = False
                blockers.append("fire_execution_state_changed_during_preflight")
        except Exception:
            report["both_fire_endpoints_disabled"] = False
            blockers.append("fire_execution_recheck_unavailable")

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
