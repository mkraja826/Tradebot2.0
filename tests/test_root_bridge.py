"""Offline checks for the opt-in privileged bridge.

These tests must never run a privileged command. No root status and no
enable flag is present during CI; all shell execution is mocked out.
"""
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BRIDGE = Path(__file__).resolve().parents[1] / "ops" / "tb2_root_bridge.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("tb2_root_bridge_test", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RootBridgeTests(unittest.TestCase):
    def test_default_is_disabled_no_shell_call(self):
        bridge = load_bridge()
        out = io.StringIO()
        with patch.object(bridge.os, "geteuid", return_value=1000), \
             patch.object(bridge.subprocess, "Popen") as proc, \
             redirect_stdout(out):
            code = bridge.main(["--timeout", "3", "--", "id -u"])
        self.assertEqual(code, 3)
        self.assertIn('"status":"disabled"', out.getvalue())
        proc.assert_not_called()

    def test_no_enabled_marker_disables_even_when_euid_root(self):
        bridge = load_bridge()
        out = io.StringIO()
        with patch.object(bridge.os, "geteuid", return_value=0), \
             patch.dict(bridge.os.environ, {"SUDO_USER": "tunnel_user"}), \
             patch.object(bridge, "_is_root_private_file", return_value=False), \
             patch.object(bridge.subprocess, "Popen") as proc, \
             redirect_stdout(out):
            code = bridge.main(["--timeout", "3", "--", "id -u"])
        self.assertEqual(code, 3)
        self.assertIn('"status":"disabled"', out.getvalue())
        proc.assert_not_called()

    def test_secret_labelled_output_is_masked(self):
        bridge = load_bridge()
        sanitized, clipped = bridge._clean_output(
            b"safe service: active\nAPI_SECRET=do-not-print\n"
            b"Bearer private-token-value\ndone")
        self.assertFalse(clipped)
        self.assertIn("safe service: active", sanitized)
        self.assertIn("done", sanitized)
        self.assertNotIn("do-not-print", sanitized)
        self.assertNotIn("private-token-value", sanitized)

    def test_output_is_bounded(self):
        bridge = load_bridge()
        safe, clipped = bridge._clean_output(b"x" * 9000)
        self.assertEqual(len(safe), 8000)
        self.assertTrue(clipped)

    def test_argparse_rejects_missing_delimiter_and_long_timeout(self):
        bridge = load_bridge()
        for args in ([ "--timeout", "99", "--", "id -u"],
                     ["--timeout", "2", "id -u", "extra"]):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                bridge.main(args)

    def test_approved_command_uses_clean_env_and_root_audit(self):
        bridge = load_bridge()
        out = io.StringIO()
        fake_process = SimpleNamespace(pid=1234, returncode=0)
        fake_process.communicate = lambda timeout: (b"root\n", None)
        with patch.object(bridge.os, "geteuid", return_value=0), \
             patch.dict(bridge.os.environ, {"SUDO_USER": "tunnel_user"}), \
             patch.object(bridge, "_is_root_private_file", return_value=True), \
             patch.object(bridge, "_audit") as audit, \
             patch.object(bridge.subprocess, "Popen", return_value=fake_process) as proc, \
             redirect_stdout(out):
            code = bridge.main(["--timeout", "3", "--", "id -u"])
        self.assertEqual(code, 0)
        self.assertIn('"status":"completed"', out.getvalue())
        self.assertEqual(audit.call_count, 2)
        self.assertEqual(audit.call_args_list[0].args[1], "requested")
        self.assertEqual(audit.call_args_list[1].args[1], "completed")
        cmd, kwargs = proc.call_args
        self.assertEqual(cmd[0], ["/bin/bash", "-o", "pipefail", "-c", "id -u"])
        self.assertEqual(kwargs["env"]["HOME"], "/root")
        self.assertNotIn("DELTA_DEMO_API_KEY", kwargs["env"])
        self.assertTrue(kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
