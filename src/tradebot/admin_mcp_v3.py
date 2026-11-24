"""Local stdio MCP server for native V3 account diagnostics only."""
from typing import Literal
import sqlite3
from mcp.server.fastmcp import FastMCP
from tradebot.admin_v3 import STATE,status

mcp=FastMCP('Tradebot3.0 Admin',instructions='Read-only stored V3 BTC and Gold equity diagnostics. No trade authorization, remote shell, broker changes or protection changes. Existing trading safeguards remain in force.')

@mcp.tool()
def account_status(market: Literal['BTCUSD','XAUTUSD']) -> dict:
    """Read the stored V3 equity state for one isolated market; not live trade clearance."""
    try:return status(STATE,market)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        return dict(status='unavailable',execution_authorized=False)

if __name__=='__main__':mcp.run(transport='stdio')
