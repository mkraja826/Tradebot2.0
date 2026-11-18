"""Offline Google Cloud secret runtime tests. Never access credentials/network."""
import base64
import io
import json
import os
import unittest
from unittest.mock import patch

from tradebot.gcp_runtime import (
    GCPBootstrapError, get_runtime_credentials, main, SECRET_BINDINGS,
)


class Reply(io.BytesIO):
    pass


def fake_urlopen(request, timeout):
    url = request.full_url
    if url.endswith("/project/project-id"):
        assert request.get_header("Metadata-flavor") == "Google"
        return Reply(b"tradebot2-demo-123")
    if url.endswith("/instance/service-accounts/default/token"):
        return Reply(json.dumps({"access_token": "fake_vm_metadata_token"}).encode())
    for env_name, secret_id in SECRET_BINDINGS:
        if "/secrets/" + secret_id + "/versions/latest:access" in url:
            assert request.get_header("Authorization") == "Bearer fake_vm_metadata_token"
            payload = base64.b64encode(("dummy-" + env_name).encode()).decode()
            return Reply(json.dumps({"payload": {"data": payload}}).encode())
    raise AssertionError("Unexpected network target")


class GCPRuntimeTests(unittest.TestCase):
    def test_secret_bindings_are_only_expected_three(self):
        self.assertEqual([name for name, _ in SECRET_BINDINGS],
                         ["DELTA_DEMO_API_KEY", "DELTA_DEMO_API_SECRET", "TB_API_KEY"])

    def test_loads_only_through_vm_metadata_and_secretmanager(self):
        with patch("tradebot.gcp_runtime.urlopen", side_effect=fake_urlopen):
            values = get_runtime_credentials()
        self.assertEqual(values["TB_API_KEY"], "dummy-TB_API_KEY")
        self.assertEqual(values["DELTA_DEMO_API_SECRET"],
                         "dummy-DELTA_DEMO_API_SECRET")

    def test_empty_secret_is_rejected(self):
        def no_value(request, timeout):
            if "tradebot-tb-api-key" in request.full_url:
                return Reply(json.dumps({"payload": {"data": ""}}).encode())
            return fake_urlopen(request, timeout)
        with patch("tradebot.gcp_runtime.urlopen", side_effect=no_value):
            with self.assertRaises(GCPBootstrapError):
                get_runtime_credentials()

    def test_command_receives_secrets_but_cannot_enable_demo_execution(self):
        with patch("tradebot.gcp_runtime.urlopen", side_effect=fake_urlopen):
            with patch("tradebot.gcp_runtime.os.execvpe") as exec_call:
                with patch("sys.argv", ["gcp_runtime", "--", "python",
                                        "-m", "tradebot.delta_probe", "--authenticated"]):
                    main()
        exec_call.assert_called_once()
        argv = exec_call.call_args.args
        self.assertEqual(argv[0], "python")
        self.assertEqual(argv[2]["TB_API_KEY"], "dummy-TB_API_KEY")
        self.assertEqual(argv[2]["ENABLE_DEMO_ORDERS"], "false")
        self.assertEqual(argv[2]["TB_MODEL"], "tb-deepseek-v4-1-flash")

    def test_explicit_demo_execute_fails_before_reading_secrets(self):
        with patch("tradebot.gcp_runtime.urlopen") as urlopen:
            with patch("sys.argv", ["gcp_runtime", "--", "tradebot", "run",
                                    "--mode", "demo", "--demo-execute"]):
                with self.assertRaises(SystemExit):
                    main()
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
