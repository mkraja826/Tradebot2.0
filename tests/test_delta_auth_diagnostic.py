"""Local-only regression for 401 category classification and nontrading probe."""
import io
import json
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

from tradebot.delta import DeltaDemo, DeltaError
from tradebot.delta_auth_diagnostic import (
    classify_http_error, probe_once, main
)


def http_error(payload, status=401):
    if not isinstance(payload, bytes):
        payload = json.dumps(payload).encode("utf-8")
    return HTTPError(
        "https://cdn-ind.testnet.deltaex.org/private?api_key=SECRET",
        status, "SENSITIVE SECRET IN MESSAGE", {},
        io.BytesIO(payload)
    )


class DemoAuthTests(unittest.TestCase):
    def test_explicit_error_code_only_never_prints_raw_provider_message(self):
        for code, expected in (
            ("invalid_api_key", "INVALID_OR_WRONG_ENV_KEY"),
            ("UnauthorizedApiAccess", "KEY_PERMISSION_DENIED"),
            ("ip_not_whitelisted_for_api_key", "SOURCE_IP_NOT_WHITELISTED"),
            ("SignatureExpired", "SIGNATURE_EXPIRED"),
            ("signature_mismatch", "SIGNATURE_MISMATCH"),
        ):
            with self.subTest(code=code):
                response = {
                    "error": {"code": code,
                              "message": "private ip 203.0.113.50 key SECRET_ACCOUNT"},
                    "account_number": "PRIVATE_ACCOUNT_ID",
                }
                result = classify_http_error(http_error(response))
                self.assertEqual(result, ("401", expected))
                self.assertNotIn("203.0.113", str(result))
                self.assertNotIn("SECRET", str(result))

    def test_unrecognized_or_malformed_error_is_redacted(self):
        for payload in (
            {"error": {"code": "SECRET_USER_NAME"}},
            {"error": {"message": "IP 1.2.3.4"}},
            {"error": ["private"]},
            {"error": None},
            b"<html>PRIVATE_ACCOUNT_ID</html>",
            b"{" + b"x" * 100_000,
            {},
        ):
            with self.subTest(payload=str(payload)[:30]):
                status, code = classify_http_error(http_error(payload))
                self.assertEqual(status, "401")
                self.assertEqual(code, "UNKNOWN_OR_REDACTED")

    def test_simple_string_error_supported_but_not_freeform_message(self):
        self.assertEqual(classify_http_error(http_error(
            {"error": "invalid_api_key", "message": "SECRET"})),
            ("401", "INVALID_OR_WRONG_ENV_KEY"))
        self.assertEqual(classify_http_error(http_error(
            {"error": "invalid_api_key I AM SECRET"})),
            ("401", "UNKNOWN_OR_REDACTED"))

    def test_only_one_signed_get_with_no_order_path(self):
        exchange = DeltaDemo(api_key="fake", api_secret="fake",
                             allow_orders=False)
        calls = []
        def get(method, path, *, auth):
            calls.append((method, path, auth))
            return {"result": {"user_id": 1001}}
        with patch.object(exchange, "_request", side_effect=get):
            result = probe_once(exchange)
        self.assertEqual(result, {"status": "SIGNED_GET_SUCCEEDED",
                                  "reason": "NONE"})
        self.assertEqual(calls, [("GET", "/v2/users/trading_preferences", True)])

    def test_private_http_exception_is_classified_only(self):
        exchange = DeltaDemo(api_key="fake", api_secret="fake",
                             allow_orders=False)
        err = http_error({"error": {"code": "ip_not_whitelisted_for_api_key",
                                   "message": "private vm ip 10.4.9.5"}})
        def forbidden(*args, **kwargs):
            raise DeltaError("DO NOT LEAK BODY") from err
        with patch.object(exchange, "_request", side_effect=forbidden):
            result = probe_once(exchange)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["http_status"], "401")
        self.assertEqual(result["reason"], "SOURCE_IP_NOT_WHITELISTED")
        self.assertNotIn("10.4.9.5", json.dumps(result))
        self.assertNotIn("DO NOT", json.dumps(result))

    def test_bad_schema_and_non_demo_client_fail_closed(self):
        exchange = DeltaDemo(api_key="fake", api_secret="fake",
                             allow_orders=False)
        with patch.object(exchange, "_request", return_value={"result": {}}):
            self.assertEqual(probe_once(exchange)["reason"],
                             "ACCOUNT_SCHEMA_UNVERIFIED")
        exchange.allow_orders = True
        self.assertEqual(probe_once(exchange)["reason"], "INVALID_READ_ONLY_CLIENT")

    def test_cli_never_prints_credentials_or_trading_enabled(self):
        with patch.dict("os.environ", {"DELTA_DEMO_API_KEY": "SECRETKEY",
                                       "DELTA_DEMO_API_SECRET": "SECRETSECRET"}):
            with patch("tradebot.delta_auth_diagnostic.probe_once",
                       return_value={"status": "BLOCKED",
                                     "reason": "KEY_PERMISSION_DENIED",
                                     "http_status": "401"}):
                with patch("builtins.print") as printer:
                    self.assertEqual(main(), 2)
        output = "\n".join(str(call) for call in printer.call_args_list)
        self.assertIn("KEY_PERMISSION_DENIED", output)
        self.assertIn("TRADING_ENABLED: false", output)
        self.assertNotIn("SECRETKEY", output)
        self.assertNotIn("SECRETSECRET", output)


if __name__ == "__main__":
    unittest.main()
