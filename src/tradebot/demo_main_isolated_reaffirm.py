"""One-time, operator-confirmed Delta India DEMO Main isolated-mode reaffirmation.

This command is NOT trading activation. Only a signed PUT to the documented
/v2/users/margin_mode is permitted after two authenticated full-account flat
samples, matching current-user identity, active protection services, a
disabled FIRE dashboard, and typed local consent. Never send an order.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

from tradebot.delta import DEMO_API, DeltaDemo, DeltaError
from tradebot.fire_account_guard import require_flat_demo_account_for_configuration
from tradebot.fire_commission_preflight import _services_active, _fire_disabled
from tradebot.signed_margin_mode import _user_id

APPROVAL = "REAFFIRM MAIN DEMO ISOLATED"
MARKER = "main-demo-isolated-reaffirm-once.lock"
INTERVAL_SECONDS = 11


class AccountSettingRejected(ValueError):
    pass


def _current_main_key_user(readonly):
    response = readonly._request(
        "GET", "/v2/users/trading_preferences", auth=True
    )
    result = response.get("result") if type(response) is dict else None
    if type(result) is not dict:
        raise AccountSettingRejected("signed_main_identity_unverified")
    try:
        uid = _user_id(result.get("user_id"))
    except ValueError:
        raise AccountSettingRejected("signed_main_identity_unverified") from None
    # The original operator separately confirmed this API key is scoped to
    # Main. Reject any signed contradictory evidence; do not guess when these
    # optional API fields are absent.
    if (result.get("is_sub_account") is True
            or (result.get("account_name") is not None
                and result.get("account_name") not in ("Main", "Main Account"))):
        raise AccountSettingRejected("signed_identity_not_main")
    return uid, result.get("margin_mode")


class IsolatedOnlyDeltaMutation(DeltaDemo):
    """Permit one specific settings PUT; all broker order paths are denied."""

    def __init__(self, api_key, api_secret):
        super().__init__(
            api_key=api_key, api_secret=api_secret, allow_orders=True
        )
        self._used = False

    def _request(self, method, path, *, params=None, payload=None, auth=False):
        valid = (
            method == "PUT"
            and path == "/v2/users/margin_mode"
            and auth is True
            and params is None
            and type(payload) is dict
            and set(payload) == {"margin_mode", "subaccount_user_id"}
            and payload["margin_mode"] == "isolated"
            and type(payload["subaccount_user_id"]) is str
            and payload["subaccount_user_id"].isdecimal()
            and int(payload["subaccount_user_id"]) > 0
            and not self._used
        )
        if not valid:
            raise AccountSettingRejected("account_setting_request_not_allowed")
        self._used = True  # No second PUT after timeout or uncertain outcome.
        return super()._request(
            method, path, payload=payload, auth=True
        )

    def reaffirm_isolated(self, user):
        reply = self._request(
            "PUT", "/v2/users/margin_mode", auth=True,
            payload={"margin_mode": "isolated", "subaccount_user_id": user},
        )
        result = reply.get("result") if type(reply) is dict else None
        if (type(result) is not dict
                or _user_id(result.get("id")) != user
                or result.get("margin_mode") != "isolated"):
            raise AccountSettingRejected("main_margin_acknowledgement_unverified")
        return True


def _exclusive_marker(root):
    path = root / MARKER
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, b"one authenticated DEMO Main isolated margin request consumed\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    folder = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def reaffirm_main_demo(
        data_dir, *, execute=False, approval=None, broker_factory=DeltaDemo,
        mutation_factory=IsolatedOnlyDeltaMutation,
        full_flatness=require_flat_demo_account_for_configuration,
        services=_services_active, fire_disabled=_fire_disabled,
        pause=time.sleep, monotonic=time.monotonic):
    """Prepare or execute exactly one settings mutation, never any order."""
    report = {
        "environment": "delta-india-demo",
        "mode": "read_only" if not execute else "one_time_account_setting",
        "status": "blocked", "blockers": [],
        "main_account_identity_consistent": False,
        "account_wide_flat_twice": False,
        "dash_fire_disabled": False,
        "protective_services_active": False,
        "one_time_marker_consumed": False,
        "setting_request_attempted": False,
        "isolated_setting_acknowledged": False,
        "post_change_readback_isolated": False,
        "broker_orders_submitted": False,
        "trading_enabled": False,
    }
    blocks = report["blockers"]
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink():
        blocks.append("trusted_original_data_dir_required")
        return report
    root = root.resolve()
    report["one_time_marker_consumed"] = os.path.lexists(root / MARKER)
    if report["one_time_marker_consumed"]:
        blocks.append("main_margin_reaffirm_already_attempted")
        return report
    key, secret = os.getenv("DELTA_DEMO_API_KEY", ""), os.getenv("DELTA_DEMO_API_SECRET", "")
    client = broker_factory(api_key=key, api_secret=secret, allow_orders=False)
    if (getattr(client, "base_url", None) != DEMO_API
            or getattr(client, "allow_orders", None) is not False):
        blocks.append("readonly_demo_broker_required")
        return report
    try:
        report["protective_services_active"] = services() is True
        report["dash_fire_disabled"] = fire_disabled() is True
    except Exception:
        pass
    if not report["protective_services_active"]:
        blocks.append("watchdog_collector_dashboard_not_verified")
    if not report["dash_fire_disabled"]:
        blocks.append("existing_fire_execution_not_disabled")
    if blocks:
        return report
    try:
        first_user, mode = _current_main_key_user(client)
        if mode is not None and mode != "isolated":
            blocks.append("unexpected_current_margin_mode")
            return report
        before = monotonic()
        one = full_flatness(client)
        if (type(one) is not dict
                or one.get("account_flat_verified") is not True
                or one.get("open_positions") != 0
                or one.get("open_orders") != 0
                or set(one.get("checked_markets", [])) != {"BTCUSD", "XAUTUSD"}):
            raise AccountSettingRejected("first_full_account_flatness_not_verified")
        pause(INTERVAL_SECONDS)
        elapsed = monotonic() - before
        if (type(elapsed) not in (int, float)
                or not math.isfinite(elapsed)
                or elapsed < INTERVAL_SECONDS or elapsed > 40):
            raise AccountSettingRejected("flatness_samples_not_spaced")
        two = full_flatness(client)
        if (type(two) is not dict
                or two.get("account_flat_verified") is not True
                or two.get("open_positions") != 0
                or two.get("open_orders") != 0
                or set(two.get("checked_markets", [])) != {"BTCUSD", "XAUTUSD"}):
            raise AccountSettingRejected("second_full_account_flatness_not_verified")
        second_user, second_mode = _current_main_key_user(client)
        if second_user != first_user or (
                second_mode is not None and second_mode != "isolated"):
            raise AccountSettingRejected("signed_current_account_identity_changed")
        report["main_account_identity_consistent"] = True
        report["account_wide_flat_twice"] = True
        if not execute:
            report["status"] = "awaiting_one_time_operator_confirmation"
            return report
        if approval != APPROVAL:
            blocks.append("operator_confirmation_required")
            return report
        if os.path.lexists(root / MARKER):
            blocks.append("main_margin_reaffirm_already_attempted")
            return report
        _exclusive_marker(root)
        report["one_time_marker_consumed"] = True
        report["setting_request_attempted"] = True
        # Only mutation-capable object in this module allows exactly one
        # PUT on /v2/users/margin_mode; order POST/DELETE are impossible.
        writer = mutation_factory(api_key=key, api_secret=secret)
        if getattr(writer, "base_url", None) != DEMO_API:
            raise AccountSettingRejected("unexpected_broker_hostname")
        writer.reaffirm_isolated(first_user)
        report["isolated_setting_acknowledged"] = True
        # A second signed GET is independent evidence of current state if
        # and only if Delta actually returns an explicit margin_mode field.
        post_user, post_mode = _current_main_key_user(client)
        report["post_change_readback_isolated"] = (
            post_user == first_user and post_mode == "isolated"
        )
        report["status"] = (
            "isolated_setting_and_signed_readback_verified"
            if report["post_change_readback_isolated"]
            else "isolated_setting_acknowledged_readback_absent"
        )
        return report
    except (DeltaError, AccountSettingRejected, ValueError, TypeError,
            OSError, KeyError, OverflowError):
        blocks.append(
            "account_setting_outcome_uncertain" if report["setting_request_attempted"]
            else "account_identity_or_exposure_unverified"
        )
        return report
    except Exception:
        blocks.append(
            "account_setting_outcome_uncertain" if report["setting_request_attempted"]
            else "broker_preflight_unavailable"
        )
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--reaffirm-main-demo-isolated", action="store_true")
    args = parser.parse_args(argv)
    approval = None
    if args.reaffirm_main_demo_isolated:
        if not sys.stdin.isatty():
            parser.error("Local interactive operator terminal required")
        print("ACCOUNT SETTING MUTATION: Delta India DEMO Main / Isolated only.")
        print("No orders. Only one margin-mode PUT if flatness passes twice.")
        approval = input("Type " + APPROVAL + " to proceed: ")
    report = reaffirm_main_demo(
        args.data_dir, execute=args.reaffirm_main_demo_isolated,
        approval=approval
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"].startswith("isolated_setting_") or (
        report["status"] == "awaiting_one_time_operator_confirmation") else 2


if __name__ == "__main__":
    raise SystemExit(main())
