"""Exercise plugin discovery and argument validation over the actual MCP transport."""
import asyncio
from importlib.util import find_spec
import sys
import unittest


@unittest.skipUnless(find_spec("mcp"), "Install .[plugin] for MCP transport tests")
class ChatPluginTests(unittest.TestCase):
    def test_stdio_discovery_and_rejected_symbol(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def check():
            params = StdioServerParameters(command=sys.executable, args=["-m","tradebot.chat_plugin"])
            async with stdio_client(params) as streams, ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = {t.name:t for t in result.tools}
                self.assertEqual(set(tools), {"fire_demo","review_fire","fire_history","market_status"})
                self.assertTrue(tools["fire_demo"].annotations.idempotentHint)
                self.assertFalse(tools["fire_demo"].annotations.readOnlyHint)
                invalid = await session.call_tool("fire_demo", {"symbol":"BTCUSDT","fire_id":"bad"})
                self.assertTrue(invalid.isError)
        asyncio.run(check())
