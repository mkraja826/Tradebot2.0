"""Private stdio MCP adapter for the local Delta demo dashboard."""
import json
from http.client import HTTPConnection
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

Market = Literal["BTCUSD", "XAUTUSD"]
server = FastMCP("Trading Bot 2.0", instructions=(
    "Use read tools to investigate and compare trades. Only fire_demo creates a Delta demo order "
    "and requests a paid GPT decision. Use it only for an explicit new trade in a named market. "
    "On timeout recover the original Fire ID. Separate decision-time evidence from later prices."))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)


def dashboard(path, *, submit=False):
    # Fixed loopback destination, no forwarded credentials, redirects or caller-supplied URLs.
    connection = HTTPConnection("127.0.0.1", 8765, timeout=60)
    try:
        headers = {"Origin":"http://127.0.0.1:8765","X-Tradebot-Action":"fire-execute"} if submit else {}
        connection.request("POST" if submit else "GET", path, body=b"" if submit else None, headers=headers)
        response = connection.getresponse()
        if response.status not in (200,202):
            raise ValueError(f"Dashboard returned HTTP {response.status}; check the Fire receipt and bot status.")
        return json.loads(response.read())
    finally:
        connection.close()


@server.tool(annotations=READ)
def market_status(symbol: Market) -> dict:
    """Read the selected demo market quote, levels, account positions and latest FIRE receipt."""
    data = dashboard("/api/chart-desk?"+urlencode({"symbol":symbol,"period":"5m"}))
    latest = dashboard("/api/fire" if symbol=="BTCUSD" else "/api/fire/XAUTUSD")
    return {"symbol":symbol,"quote":data.get("quote"),"positions_and_exits":data.get("account"),
            "historical_levels":data.get("historical_levels"),"latest_fire":latest}


@server.tool(annotations=READ)
def fire_history(symbol: Market, page: Annotated[int, Field(ge=0,le=1000000)] = 0) -> dict:
    """List up to 40 historical Fire receipts, newest first, including rejected attempts."""
    data = dashboard("/api/chart-desk?"+urlencode({"symbol":symbol,"page":page}))
    return {"symbol":symbol,"page":page,"receipts":data["trades"]}


@server.tool(annotations=WRITE)
def fire_demo(symbol: Market, fire_id: UUID) -> dict:
    """Request one GPT-decided demo trade. Generate a UUID for this explicit request and retain it.
    Reuse the same symbol and ID after interruptions. Acceptance only reserves the request."""
    return dashboard(f"/api/plugin/fire/{symbol}/{fire_id.hex}", submit=True)


@server.tool(annotations=READ)
def review_fire(symbol: Market, fire_id: UUID) -> dict:
    """Look up an exact Fire ID. Read its saved thesis, indicators, broker fill evidence and scorecard.
    A missing confirmed exit or net P&L means unknown. Compare trades by looking up both IDs."""
    return dashboard(f"/api/plugin/review/{symbol}/{fire_id.hex}")


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
