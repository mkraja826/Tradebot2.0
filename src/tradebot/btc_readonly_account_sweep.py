"""Two-sweep signed DEMO account flatness diagnostic; no trade permission."""
import math
import time
from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.demo_main_isolated_reaffirm import _current_main_key_user
from tradebot.fire_exposure_only_probe import observe_exposure_without_margin

MIN_GAP = 11
MAX_GAP = 40


def observe_flat_twice(exchange, *, sample=observe_exposure_without_margin,
                       identify=_current_main_key_user,
                       pause=time.sleep, monotonic=time.monotonic):
    result = {
        "mode": "read_only_two_sweep",
        "status": "blocked",
        "reason": "unverified",
        "main_account_identity_stable": False,
        "two_sample_flatness_observed": False,
        "broker_margin_verified": False,
        "financial_reconciliation_verified": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "broker_order_mutations": False,
        "ai_calls": 0,
    }
    if (not isinstance(exchange, DeltaDemo)
            or exchange.base_url != DEMO_API or exchange.allow_orders is not False):
        result["reason"] = "read_only_demo_client_required"
        return result
    def flat(report):
        return (
            type(report) is dict
            and report.get("status") == "signed_exposure_snapshot_observed"
            and report.get("blocker") == "none_in_this_single_snapshot"
            and report.get("account_wide_margined_positions_nonzero") == 0
            and report.get("account_wide_open_or_pending_orders") == 0
            and report.get("margined_realtime_consistent") is True
            and report.get("any_exposure_observed") is False
            and report.get("realtime_fire_position_sizes")
                == {"BTCUSD":"0", "XAUTUSD":"0"}
        )
    try:
        user, mode = identify(exchange)
        if mode not in (None, "isolated"):
            result["reason"] = "signed_margin_mode_contradicts_owner"
            return result
        began = monotonic()
        first = sample(exchange)
        if not flat(first):
            result["reason"] = "first_account_exposure_unverified"
            return result
        pause(MIN_GAP)
        gap = monotonic() - began
        if type(gap) not in (int, float) or not math.isfinite(gap) or not MIN_GAP <= gap <= MAX_GAP:
            result["reason"] = "sample_spacing_unverified"
            return result
        second = sample(exchange)
        if not flat(second):
            result["reason"] = "second_account_exposure_unverified"
            return result
        next_user, next_mode = identify(exchange)
        if next_user != user or next_mode not in (None, "isolated"):
            result["reason"] = "signed_account_identity_changed"
            return result
        result["main_account_identity_stable"] = True
        result["two_sample_flatness_observed"] = True
        result["status"] = "two_signed_flat_snapshots_not_release_authority"
        result["reason"] = "signed_margin_and_other_release_checks_still_required"
    except Exception:
        result["reason"] = "signed_account_exposure_unavailable"
    return result
