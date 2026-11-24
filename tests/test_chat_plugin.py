"""Exercise plugin discovery and argument validation over the actual MCP transport."""
import asyncio
from importlib.util import find_spec
import sys
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("mcp"), "Install .[plugin] for MCP transport tests")
class ChatPluginTests(unittest.TestCase):
    def test_equity_checkpoint_exposes_only_allowlisted_non_authorizing_fields(self):
        from tradebot.chat_plugin import equity_checkpoint_status
        source = {
            "status": "checkpoint_missed",
            "as_of": "2026-11-22T10:30:00+00:00",
            "daily_checkpoint": "verified",
            "weekly_checkpoint": "missed_window",
            "observation_status": "fresh",
            "latest_receipt_status": "verified",
            "database_integrity": "verified",
            "checkpoint_prerequisites_met": False,
            "blocking_conditions": ["weekly_checkpoint_missed_window"],
            "alert_codes": ["missed_weekly_checkpoint"],
            "equity_usd": "SECRET_ACCOUNT_BALANCE",
            "receipt": {"api_key": "PRIVATE_API_KEY"},
            "trade_authorized": True,
            "safe_to_enable_fire": True,
        }
        with patch("tradebot.chat_plugin.dashboard", return_value=source) as get:
            report = equity_checkpoint_status()
        get.assert_called_once_with("/api/risk/checkpoints")
        self.assertEqual(report["weekly_checkpoint"], "missed_window")
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["safe_to_enable_fire"])
        self.assertFalse(report["ready_for_unattended_trading"])
        self.assertNotIn("PRIVATE_API_KEY", str(report))
        self.assertNotIn("SECRET_ACCOUNT_BALANCE", str(report))

    def test_demo_loss_warning_does_not_replace_raw_checkpoint_or_authorize(self):
        from tradebot.chat_plugin import equity_checkpoint_status
        codes = ["equity_loss_limit_breached", "watchdog_protection_unverified"]
        source = {"blocking_conditions": codes, "alert_codes": codes,
                  "checkpoint_prerequisites_met": False}
        with patch("tradebot.chat_plugin.dashboard", return_value=source):
            report = equity_checkpoint_status()
        self.assertEqual(report["demo_equity_loss_warnings"], ["equity_loss_limit_breached"])
        self.assertEqual(report["blocking_conditions"], codes)
        self.assertFalse(report["checkpoint_is_execution_admission"])
        self.assertFalse(report["trade_authorized"])

    def test_empty_checkpoint_result_never_authorizes(self):
        from tradebot.chat_plugin import equity_checkpoint_status
        with patch("tradebot.chat_plugin.dashboard", return_value={}):
            report = equity_checkpoint_status()
        self.assertIsNone(report["status"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_root_command_uses_private_socket_and_bounded_reply(self):
        import json
        from tradebot.chat_plugin import admin_root_shell
        class Socket:
            sent = b""
            connected = ""
            timeout = None
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def settimeout(self, n): self.timeout = n
            def connect(self, path): self.connected = path
            def sendall(self, data): self.sent += data
            def recv(self, size):
                payload = (b'{"status":"completed","exit_code":0,"output":"0",'
                           b'"truncated":false,"command_sha256":"' + b'a'*64 + b'"}\n')
                if hasattr(self, 'read'): return b''
                self.read = True
                return payload
        sock = Socket()
        with patch("tradebot.chat_plugin.socket.socket", return_value=sock) as call:
            result = admin_root_shell("id -u", 5)
        call.assert_called_once()
        self.assertEqual(sock.connected, "/run/tb2-root-admin.sock")
        self.assertEqual(sock.timeout, 12)
        self.assertEqual(json.loads(sock.sent), {"command":"id -u","timeout_seconds":5})
        self.assertTrue(result["root_access_active"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"], "0")
        self.assertEqual(result["command_sha256"], "a"*64)

    def test_root_command_fails_closed_when_socket_unavailable(self):
        from tradebot.chat_plugin import admin_root_shell
        with patch("tradebot.chat_plugin.socket.socket", side_effect=OSError("private-path")):
            reply = admin_root_shell("id -u")
        self.assertFalse(reply["root_access_active"])
        self.assertEqual(reply["status"], "root_socket_unavailable_or_rejected")
        self.assertNotIn("private-path", str(reply))

    def test_root_command_rejects_malformed_params_without_execution(self):
        from tradebot.chat_plugin import admin_root_shell
        for cmd, seconds in (("", 5), ("a"*4100, 5), ("id -u" + chr(0) + "x", 5),
                             ("id -u", 0), ("id -u", 60)):
            with self.subTest(cmd=repr(cmd)[:25], seconds=seconds):
                with patch("tradebot.chat_plugin.socket.socket") as call:
                    with self.assertRaises(ValueError):
                        admin_root_shell(cmd, seconds)
                    call.assert_not_called()

    def test_root_command_rejects_untrusted_response(self):
        from tradebot.chat_plugin import admin_root_shell
        class Socket:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def settimeout(self, n): pass
            def connect(self, path): pass
            def sendall(self, data): pass
            def recv(self, size): return b'{"status":"completed","exit_code":0,"output":42}\n'
        with patch("tradebot.chat_plugin.socket.socket", return_value=Socket()):
            with self.assertRaises(ValueError):
                admin_root_shell("id -u", 1)

    def test_stdio_discovery_and_rejected_symbol(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def check():
            params = StdioServerParameters(command=sys.executable, args=["-m","tradebot.chat_plugin"])
            async with stdio_client(params) as streams, ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = {t.name:t for t in result.tools}
                self.assertEqual(set(tools), {"fire_demo","review_fire","fire_history","market_status","equity_checkpoint_status","subaccount_equity_status","admin_root_shell"})
                self.assertTrue(tools["fire_demo"].annotations.idempotentHint)
                self.assertFalse(tools["fire_demo"].annotations.readOnlyHint)
                self.assertFalse(tools["admin_root_shell"].annotations.readOnlyHint)
                self.assertTrue(tools["admin_root_shell"].annotations.destructiveHint)
                invalid = await session.call_tool("fire_demo", {"symbol":"BTCUSDT","fire_id":"bad"})
                self.assertTrue(invalid.isError)
        asyncio.run(check())
