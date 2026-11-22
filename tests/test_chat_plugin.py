"""Exercise plugin discovery and argument validation over the actual MCP transport."""
import asyncio
from importlib.util import find_spec
import sys
from types import SimpleNamespace
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

    def test_empty_checkpoint_result_never_authorizes(self):
        from tradebot.chat_plugin import equity_checkpoint_status
        with patch("tradebot.chat_plugin.dashboard", return_value={}):
            report = equity_checkpoint_status()
        self.assertIsNone(report["status"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_root_command_uses_only_local_sudo_bridge_and_no_process_secrets(self):
        from tradebot.chat_plugin import admin_root_shell
        raw = (
            b'{"status":"completed","exit_code":0,"output":"0",'
            b'"truncated":false,"command_sha256":"'
            + b'a'*64 + b'"}'
        )
        with patch("tradebot.chat_plugin.subprocess.run",
                   return_value=SimpleNamespace(
                       returncode=0, stdout=raw, stderr=b"")) as call:
            result = admin_root_shell("id -u", 5)
        self.assertTrue(result["root_access_active"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"], "0")
        args, kw = call.call_args
        self.assertEqual(args[0], [
            "/usr/bin/sudo", "-n", "/usr/local/sbin/tb2-root-bridge",
            "--timeout", "5", "--", "id -u",
        ])
        self.assertFalse(kw["check"])
        self.assertEqual(kw["cwd"], "/")
        self.assertEqual(kw["input"], b"")
        self.assertEqual(kw["env"], {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C", "LC_ALL": "C",
        })
        self.assertFalse(result.get("trading_enabled", False))

    def test_root_command_fails_closed_when_sudo_unavailable(self):
        from tradebot.chat_plugin import admin_root_shell
        with patch("tradebot.chat_plugin.subprocess.run",
                   return_value=SimpleNamespace(
                       returncode=1, stdout=b"", stderr=b"unknown username")):
            reply = admin_root_shell("id -u")
        self.assertFalse(reply["root_access_active"])
        self.assertEqual(reply["status"],
                         "root_bridge_not_configured_or_rejected")
        self.assertNotIn("unknown username", str(reply))

    def test_root_command_rejects_malformed_params_without_execution(self):
        from tradebot.chat_plugin import admin_root_shell
        for cmd, seconds in (("", 5), ("a"*4100, 5), ("id -u\\x00x", 5),
                             ("id -u", 0), ("id -u", 60)):
            with self.subTest(cmd=repr(cmd)[:25], seconds=seconds):
                with patch("tradebot.chat_plugin.subprocess.run") as call:
                    with self.assertRaises(ValueError):
                        admin_root_shell(cmd, seconds)
                    call.assert_not_called()

    def test_stdio_discovery_and_rejected_symbol(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def check():
            params = StdioServerParameters(command=sys.executable, args=["-m","tradebot.chat_plugin"])
            async with stdio_client(params) as streams, ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = {t.name:t for t in result.tools}
                self.assertEqual(set(tools), {"fire_demo","review_fire","fire_history","market_status","equity_checkpoint_status","admin_root_shell"})
                self.assertTrue(tools["fire_demo"].annotations.idempotentHint)
                self.assertFalse(tools["fire_demo"].annotations.readOnlyHint)
                self.assertFalse(tools["admin_root_shell"].annotations.readOnlyHint)
                self.assertTrue(tools["admin_root_shell"].annotations.destructiveHint)
                invalid = await session.call_tool("fire_demo", {"symbol":"BTCUSDT","fire_id":"bad"})
                self.assertTrue(invalid.isError)
        asyncio.run(check())
