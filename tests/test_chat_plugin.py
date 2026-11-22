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

    def test_empty_checkpoint_result_never_authorizes(self):
        from tradebot.chat_plugin import equity_checkpoint_status
        with patch("tradebot.chat_plugin.dashboard", return_value={}):
            report = equity_checkpoint_status()
        self.assertIsNone(report["status"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_stdio_discovery_and_rejected_symbol(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def check():
            params = StdioServerParameters(command=sys.executable, args=["-m","tradebot.chat_plugin"])
            async with stdio_client(params) as streams, ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = {t.name:t for t in result.tools}
                self.assertEqual(set(tools), {"fire_demo","review_fire","fire_history","market_status","equity_checkpoint_status"})
                self.assertTrue(tools["fire_demo"].annotations.idempotentHint)
                self.assertFalse(tools["fire_demo"].annotations.readOnlyHint)
                invalid = await session.call_tool("fire_demo", {"symbol":"BTCUSDT","fire_id":"bad"})
                self.assertTrue(invalid.isError)
        asyncio.run(check())
