"""Signed account-scoped margin-mode evidence without deprecated /v2/profile.

Delta India stopped API-key access to GET /v2/profile on 2026-08-19.
Correlate two currently documented authenticated read-only endpoints:
  GET /v2/users/trading_preferences -> current user_id
  GET /v2/sub_accounts -> exact matching current-user margin_mode if listed.\nWhen the main account is absent, only its *explicit* signed preferences\nmargin_mode may provide the account-scoped proof.
Never infer isolated margin from empty positions or a different account row.\nOnly signed GETs occur here, including when called after a broker fill by the\nseparately authorized execution controller. Read-only audit callers must still\nrequire allow_orders=False before using this helper.
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
    """Fail closed unless two signed GETs prove current user margin consistently."""
    if (getattr(exchange, "base_url", None) != DEMO_API
            or type(getattr(exchange, "allow_orders", None)) is not bool):
        raise MarginModeEvidenceError("delta_demo_client_required")

    # Never call GET /v2/profile: officially inaccessible to API keys.
    preferences = exchange._request(
        "GET", "/v2/users/trading_preferences", auth=True
    )
    if not isinstance(preferences, dict) or not isinstance(
            preferences.get("result"), dict):
        raise MarginModeEvidenceError("signed_account_preferences_unverified")
    user = _user_id(preferences["result"].get("user_id"))
    # The separate official Delta MCP account tool describes an explicit
    # margin_mode in trading preferences, while the documented REST example
    # does not guarantee this optional field. Never infer it from auto-topup,
    # portfolio availability, empty positions, or the account type.
    direct_mode = preferences["result"].get("margin_mode")
    if direct_mode is not None and direct_mode not in ("isolated", "portfolio", "cross"):
        raise MarginModeEvidenceError("signed_margin_mode_unverified")

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
    if len(found) > 1:
        raise MarginModeEvidenceError("signed_account_identity_not_unique")
    if not found:
        # A main-account signed /v2/sub_accounts list may validly contain no
        # matching main account. Use ONLY an explicit signed mode on the
        # authenticated current user's preferences, never other account rows.
        if direct_mode is None:
            raise MarginModeEvidenceError("signed_account_identity_not_unique")
        return direct_mode
    mode = found[0].get("margin_mode")
    if mode not in ("isolated", "portfolio", "cross"):
        raise MarginModeEvidenceError("signed_margin_mode_unverified")
    if direct_mode is not None and direct_mode != mode:
        raise MarginModeEvidenceError("signed_margin_mode_conflict")
    return mode
