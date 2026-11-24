"""One authenticated DEMO account GET; classify errors without leaking response data.

The GitHub-hosted broker audit returned HTTP 401. This diagnostic is one
additional look at the provider's *fixed error code*, not the raw error
message, URL, account, key, whitelist IP, signature or response body.

No order endpoint, margin change, IP change, wallet read or model call.
"""
import json
import os
import sys
from urllib.error import HTTPError

from tradebot.delta import DeltaDemo, DeltaError, DEMO_API

# Known codes from Delta India documentation (exact provider tokens only).
# Never emit a free-form provider message, nor an API-key-scoped IP string.
SAFE_CATEGORIES = {
    "invalid_api_key": "INVALID_OR_WRONG_ENV_KEY",
    "unauthorizedapiaccess": "KEY_PERMISSION_DENIED",
    "ip_not_whitelisted_for_api_key": "SOURCE_IP_NOT_WHITELISTED",
    "signatureexpired": "SIGNATURE_EXPIRED",
    "signature_expired": "SIGNATURE_EXPIRED",
    "signaturemismatch": "SIGNATURE_MISMATCH",
    "signature_mismatch": "SIGNATURE_MISMATCH",
    "invalid_signature": "SIGNATURE_MISMATCH",
}


def classify_http_error(error):
    """Return only status and fixed known category. Never echo raw body."""
    if not isinstance(error, HTTPError):
        return "HTTP_UNAVAILABLE", "UNKNOWN_OR_REDACTED"
    http = error.code if type(error.code) is int and error.code in (
        400, 401, 403, 404, 408, 429, 500, 502, 503
    ) else "OTHER"
    category = "UNKNOWN_OR_REDACTED"
    try:
        data = json.loads(error.read(4096))
        if type(data) is dict:
            problem = data.get("error")
            if type(problem) is dict:
                code = problem.get("code")
            elif type(problem) is str:
                code = problem
            else:
                code = None
            if type(code) is str:
                category = SAFE_CATEGORIES.get(code.lower(), category)
    except (OSError, ValueError, UnicodeDecodeError, TypeError):
        pass
    return str(http), category


def probe_once(exchange):
    """Single signed, read-only preferences request, with sanitized evidence."""
    if (type(exchange) is not DeltaDemo
            or getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        return {"status": "BLOCKED", "reason": "INVALID_READ_ONLY_CLIENT"}
    try:
        response = exchange._request(
            "GET", "/v2/users/trading_preferences", auth=True
        )
        result = response.get("result") if type(response) is dict else None
        if type(result) is dict and (
                (type(result.get("user_id")) is int and result["user_id"] > 0)
                or (type(result.get("user_id")) is str
                    and result["user_id"].isdecimal()
                    and int(result["user_id"]) > 0)):
            return {"status": "SIGNED_GET_SUCCEEDED", "reason": "NONE"}
        return {"status": "BLOCKED", "reason": "ACCOUNT_SCHEMA_UNVERIFIED"}
    except DeltaError as exc:
        cause = exc.__cause__
        if isinstance(cause, HTTPError):
            status, reason = classify_http_error(cause)
            return {"status": "BLOCKED", "reason": reason,
                    "http_status": status}
        return {"status": "BLOCKED", "reason": "DELTA_READ_UNAVAILABLE"}
    except Exception:
        # Treat malformed and unexpected network/application errors equally;
        # never include the offending exception, path or response payload.
        return {"status": "BLOCKED", "reason": "SIGNED_GET_UNVERIFIED"}


def main():
    key = os.getenv("DELTA_DEMO_API_KEY", "")
    secret = os.getenv("DELTA_DEMO_API_SECRET", "")
    if not key or not secret:
        result = {"status": "BLOCKED", "reason": "DEMO_CREDENTIALS_MISSING"}
    else:
        result = probe_once(DeltaDemo(
            api_key=key, api_secret=secret, allow_orders=False
        ))
    # Only the result's fixed fields are printed, never the credentials.
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    print("ACCOUNT_WIDE_FLATNESS_VERIFIED: false")
    print("TRADING_ENABLED: false")
    return 0 if result["status"] == "SIGNED_GET_SUCCEEDED" else 2


if __name__ == "__main__":
    sys.exit(main())
