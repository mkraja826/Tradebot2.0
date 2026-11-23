"""Offline security tests for the private root socket adapter.

These tests never start systemd, contact the socket or run privileged commands.
"""
import importlib.util
import json
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "tb2_root_socket_server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("tb2_root_socket_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSocket:
    def __init__(self, uid, request):
        self.uid = uid
        self.remaining = request
        self.responses = []
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def getsockopt(self, level, name, length):
        return struct.pack("3i", 12345, self.uid, 1000)

    def recv(self, size):
        reply, self.remaining = self.remaining[:size], self.remaining[size:]
        return reply

    def sendall(self, data):
        self.responses.append(json.loads(data))

    @property
    def last(self):
        return self.responses[-1]


class RootSocketTests(unittest.TestCase):
    def test_foreign_uid_denied_before_shell(self):
        module = load_server()
        conn = FakeSocket(1001, b'{"command":"id -u","timeout_seconds":5}\n')
        with patch.object(module.subprocess, "run") as run:
            module.handle(conn, "support", 1000)
        self.assertEqual(conn.last["status"], "unauthorized_peer")
        run.assert_not_called()

    def test_valid_peer_uses_fixed_bridge_and_clean_env(self):
        module = load_server()
        conn = FakeSocket(1000, b'{"command":"id -u","timeout_seconds":5}\n')
        fake = SimpleNamespace(stdout=b'{"status":"completed","exit_code":0,"output":"0"}\n')
        with patch.object(module.subprocess, "run", return_value=fake) as run:
            module.handle(conn, "support", 1000)
        self.assertEqual(conn.last["status"], "completed")
        self.assertEqual(conn.last["output"], "0")
        args, kwargs = run.call_args
        self.assertEqual(args[0], [module.BRIDGE, "--timeout", "5", "--", "id -u"])
        self.assertEqual(kwargs["env"]["SUDO_USER"], "support")
        self.assertEqual(kwargs["cwd"], "/")
        self.assertEqual(kwargs["input"], b"")
        self.assertNotIn("CONTROL_PLANE_API_KEY", kwargs["env"])

    def test_invalid_requests_do_not_call_bridge(self):
        module = load_server()
        requests = [
            b'{"command":"id -u","timeout_seconds":true}\n',
            b'{"command":"id -u","timeout_seconds":31}\n',
            b'{"command":"id -u","timeout_seconds":5,"user":"root"}\n',
            b'{"command":"","timeout_seconds":5}\n',
            b'not-json\n',
            b'x' * 8200,
        ]
        for request in requests:
            with self.subTest(request=request[:40]):
                conn = FakeSocket(1000, request)
                with patch.object(module.subprocess, "run") as run:
                    module.handle(conn, "support", 1000)
                self.assertEqual(conn.last["status"], "invalid_request")
                run.assert_not_called()

    def test_failed_bridge_returns_no_stdout(self):
        module = load_server()
        conn = FakeSocket(1000, b'{"command":"id -u","timeout_seconds":5}\n')
        with patch.object(module.subprocess, "run",
                          return_value=SimpleNamespace(stdout=b"")):
            module.handle(conn, "support", 1000)
        self.assertEqual(conn.last["status"], "root_bridge_unavailable_or_rejected")
        self.assertNotIn("output", conn.last)

    def test_identity_requires_root_owned_regular_0600_file(self):
        module = load_server()
        bad = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_nlink=1)
        with patch.object(module.os, "lstat", return_value=bad):
            with self.assertRaises(PermissionError):
                module.identity()
        symlink = SimpleNamespace(st_mode=stat.S_IFLNK | 0o600, st_uid=0, st_nlink=1)
        with patch.object(module.os, "lstat", return_value=symlink):
            with self.assertRaises(PermissionError):
                module.identity()

    def test_server_cannot_start_unprivileged(self):
        module = load_server()
        with patch.object(module.os, "geteuid", return_value=1000):
            with self.assertRaises(SystemExit):
                module.main()

    def test_server_requires_systemd_socket_activation(self):
        module = load_server()
        with patch.object(module.os, "geteuid", return_value=0), \
             patch.dict(module.os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                module.main()


if __name__ == "__main__":
    unittest.main()
