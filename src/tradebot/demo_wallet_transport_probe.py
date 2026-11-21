"""One authenticated, GET-only Delta India DEMO wallet transport preflight.

This probe is intentionally NOT an equity collector, finance reconciler, trade
gate or release authority. It does not read/write SQLite or display balances.
A valid receipt attests HTTPS request timing, NOT the broker's internal equity
valuation timestamp and NOT an equity opening checkpoint.
"""
import argparse
import json
import os

from tradebot.delta import DEMO_API, DeltaDemo, DeltaReadError
from tradebot.equity_receipt import EquityReadError, validate_receipt


def probe_wallet_transport(exchange, *, validator=validate_receipt):
    """One authenticated read. All failures are sanitized and fail-closed."""
    report = {
        "environment": "delta-india-demo",
        "mode": "single_authenticated_get_only",
        "status": "unverified",
        "reason": "wallet_read_unavailable",
        "transport_receipt_verified": False,
        "broker_valuation_timestamp_verified": False,
        "opening_checkpoint_verified": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
        "broker_order_mutations": False,
        "local_ledger_mutations": False,
        "ai_calls": 0,
    }
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(
            exchange, "allow_orders", None) is not False:
        report["reason"] = "read_only_demo_client_required"
        return report
    try:
        wallet = exchange.wallet_balances()
        if type(wallet) is not dict or type(wallet.get("meta")) is not dict:
            report["reason"] = "wallet_response_unverified"
            return report
        # No amount, receipt, HTTP Date, account identifier or raw exception
        # is ever included in output. The validator inspects it in memory.
        validator(wallet["meta"].get("net_equity"), wallet.get("equity_read_receipt"))
        report["status"] = "transport_receipt_verified_not_trade_authority"
        report["reason"] = "none"
        report["transport_receipt_verified"] = True
    except DeltaReadError as exc:
        # Broker adapter exposes fixed failures for the signed wallet GET.
        report["reason"] = (exc.code if exc.code in {
            "broker_authentication_failed",
            "broker_equity_unavailable",
            "broker_equity_rejected",
        } else "wallet_read_unavailable")
    except EquityReadError as exc:
        # Preserve *only* known validated reason codes; do not leak arbitrary
        # message content from injected clients.
        allowed = {
            "clock_unverified", "broker_time_evidence_unavailable",
            "equity_read_receipt_missing", "equity_read_receipt_invalid",
            "equity_read_value_mismatch", "system_clock_jump",
            "broker_equity_read_slow", "broker_clock_or_stale_response",
            "broker_equity_response_cached", "broker_equity_read_stale",
            "equity_boundary_ambiguous",
        }
        report["reason"] = exc.code if exc.code in allowed else "wallet_transport_unverified"
    except Exception:
        report["reason"] = "wallet_read_unavailable"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    key = os.environ.get("DELTA_DEMO_API_KEY", "")
    secret = os.environ.get("DELTA_DEMO_API_SECRET", "")
    if not key or not secret:
        result = {
            "environment": "delta-india-demo",
            "mode": "single_authenticated_get_only",
            "status": "unverified",
            "reason": "demo_credentials_unavailable",
            "transport_receipt_verified": False,
            "broker_valuation_timestamp_verified": False,
            "opening_checkpoint_verified": False,
            "trade_authorized": False,
            "safe_to_enable_fire": False,
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2
    result = probe_wallet_transport(
        DeltaDemo(api_key=key, api_secret=secret, allow_orders=False)
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["transport_receipt_verified"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
