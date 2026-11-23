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



def _parent_signed_subaccount_mode(child_user, child_direct_mode, *,
                                   parent_exchange=None, expected_label=None):
    """Bind a child API identity to one signed parent-owned account row.

    The child's /v2/sub_accounts listing may omit its own user. A separate,
    authenticated, *read-only* parent API client can attest to that child's
    margin mode. A manual declaration, sibling or parent row cannot.
    """
    import os
    from tradebot.delta import DeltaDemo

    if parent_exchange is None:
        key = os.environ.get("TRADEBOT_PARENT_DEMO_API_KEY")
        secret = os.environ.get("TRADEBOT_PARENT_DEMO_API_SECRET")
        if not key or not secret:
            raise MarginModeEvidenceError("signed_current_account_margin_mode_unavailable")
        parent_exchange = DeltaDemo(api_key=key, api_secret=secret,
                                    allow_orders=False)
    if (getattr(parent_exchange, "base_url", None) != DEMO_API
            or getattr(parent_exchange, "allow_orders", None) is not False):
        raise MarginModeEvidenceError("signed_parent_readonly_demo_required")
    try:
        parent_prefs = parent_exchange._request(
            "GET", "/v2/users/trading_preferences", auth=True)
        if not isinstance(parent_prefs, dict) or not isinstance(
                parent_prefs.get("result"), dict):
            raise MarginModeEvidenceError("signed_parent_identity_unverified")
        parent_user = _user_id(parent_prefs["result"].get("user_id"))
        if parent_user == child_user:
            raise MarginModeEvidenceError("signed_parent_must_be_distinct")
        roster_reply = parent_exchange._request(
            "GET", "/v2/sub_accounts", auth=True)
        rows = roster_reply.get("result") if isinstance(roster_reply, dict) else None
        if not isinstance(rows, list) or len(rows) > 100:
            raise MarginModeEvidenceError("signed_parent_roster_unverified")
        seen = set()
        matches = []
        for row in rows:
            if not isinstance(row, dict):
                raise MarginModeEvidenceError("signed_parent_roster_unverified")
            row_id = _user_id(row.get("id"))
            if row_id in seen or row_id == parent_user:
                raise MarginModeEvidenceError("signed_parent_roster_identity_conflict")
            seen.add(row_id)
            if row_id == child_user:
                matches.append(row)
        if len(matches) != 1:
            raise MarginModeEvidenceError("signed_child_not_in_parent_roster")
        row = matches[0]
        mode = row.get("margin_mode")
        if mode not in ("isolated", "portfolio", "cross"):
            raise MarginModeEvidenceError("signed_parent_margin_mode_unverified")
        if child_direct_mode is not None and child_direct_mode != mode:
            raise MarginModeEvidenceError("signed_child_parent_margin_mode_conflict")
        if expected_label is not None:
            name = row.get("account_name")
            if (not isinstance(name, str) or
                    expected_label.lower() not in name.lower()):
                raise MarginModeEvidenceError("signed_subaccount_market_label_mismatch")
        return mode
    except MarginModeEvidenceError:
        raise
    except Exception:
        raise MarginModeEvidenceError("signed_parent_subaccount_evidence_unavailable") from None


def signed_account_margin_mode(exchange, *, parent_exchange=None):
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

    # In isolated-account mode, require both the exact authenticated child
    # identity and the separately signed parent roster, including its market
    # label. This is independent proof, not owner-attested margin configuration.
    import os
    expected_label = os.environ.get("TRADEBOT_EXPECTED_DEMO_SUBACCOUNT")
    if expected_label is not None and expected_label not in ("BTC", "GOLD"):
        raise MarginModeEvidenceError("invalid_expected_demo_subaccount")
    if expected_label is not None or parent_exchange is not None:
        return _parent_signed_subaccount_mode(
            user, direct_mode, parent_exchange=parent_exchange,
            expected_label=expected_label)

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
            # Empty (or foreign-only) subaccount listings do not establish the
            # main user's margin mode. Keep a distinct diagnosis from the
            # genuine duplicate-identity case above. Fail closed.
            return _parent_signed_subaccount_mode(
                user, direct_mode, parent_exchange=parent_exchange)
        return direct_mode
    mode = found[0].get("margin_mode")
    if mode not in ("isolated", "portfolio", "cross"):
        raise MarginModeEvidenceError("signed_margin_mode_unverified")
    if direct_mode is not None and direct_mode != mode:
        raise MarginModeEvidenceError("signed_margin_mode_conflict")
    return mode
