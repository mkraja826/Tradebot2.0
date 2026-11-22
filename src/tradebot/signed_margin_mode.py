"""Signed account-scoped margin-mode evidence without deprecated /v2/profile.

Delta India stopped API-key access to GET /v2/profile on 2026-08-19.
Correlate two currently documented authenticated read-only endpoints:
  GET /v2/users/trading_preferences -> current user_id
  GET /v2/sub_accounts -> exactly matching user.id and margin_mode.
Never infer isolated margin from empty positions or a different account row.
"""
from tradebot.delta import DEMO_API


class MarginModeEvidenceError(ValueError):
    """Fixed sanitized failure code, never a broker response body."""


def _user_id(value):
    if type(value) is int and value > 0:
        return str(value)
    if type(value) is str and value.isdecimal() and int(value) > 0:
        return str(int(value))
    raise MarginModeEvidenceError("signed_account_identity_unverified")


def signed_account_margin_mode(exchange):
    """Fail closed unless two signed GETs identify exactly one current account."""
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        raise MarginModeEvidenceError("read_only_delta_demo_client_required")

    # Never call GET /v2/profile: officially inaccessible to API keys.
    preferences = exchange._request(
        "GET", "/v2/users/trading_preferences", auth=True
    )
    if not isinstance(preferences, dict) or not isinstance(
            preferences.get("result"), dict):
        raise MarginModeEvidenceError("signed_account_preferences_unverified")
    user = _user_id(preferences["result"].get("user_id"))

    accounts = exchange._request("GET", "/v2/sub_accounts", auth=True)
    if (not isinstance(accounts, dict)
            or not isinstance(accounts.get("result"), list)
            or len(accounts["result"]) > 100):
        raise MarginModeEvidenceError("signed_subaccount_scope_unverified")
    found = []
    for row in accounts["result"]:
        if not isinstance(row, dict):
            raise MarginModeEvidenceError("signed_subaccount_scope_unverified")
        if "id" not in row:
            raise MarginModeEvidenceError("signed_subaccount_identity_unverified")
        account_id = _user_id(row["id"])
        if account_id == user:
            found.append(row)
    if len(found) != 1:
        raise MarginModeEvidenceError("signed_account_identity_not_unique")
    mode = found[0].get("margin_mode")
    if mode not in ("isolated", "portfolio", "cross"):
        raise MarginModeEvidenceError("signed_margin_mode_unverified")
    return mode
