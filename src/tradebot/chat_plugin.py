"""Private stdio MCP adapter for the local Delta demo dashboard."""
import json
import os
import subprocess
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
    "On timeout recover the original Fire ID. Separate decision-time evidence from later prices. "
    "admin_root_shell is a privileged operator tool: execute only on explicit user request, "
    "never infer trading authority or reveal secret files."))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
ROOT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


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



@server.tool(annotations=READ)
def equity_checkpoint_status() -> dict:
    """Read current UTC daily/weekly signed-wallet checkpoint health.

    This is a diagnostic only: a healthy checkpoint does not release trading.
    No wallet amounts, receipt details, API keys or ledger contents are returned.
    """
    data = dashboard("/api/risk/checkpoints")
    if not isinstance(data, dict):
        raise ValueError("Dashboard checkpoint response unavailable")
    safe_fields = (
        "status", "as_of", "daily_checkpoint", "weekly_checkpoint",
        "observation_status", "latest_receipt_status", "database_integrity",
        "checkpoint_prerequisites_met", "blocking_conditions", "alert_codes",
        "latest_observation_age_seconds", "daily_next_window_start_utc",
        "weekly_next_window_start_utc",
    )
    return {
        "environment": "delta-india-demo",
        "mode": "read_only_checkpoint_health",
        **{name: data.get(name) for name in safe_fields},
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
    }


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


@server.tool(annotations=ROOT_WRITE)
def admin_root_shell(
    command: Annotated[str, Field(min_length=1, max_length=4096)],
    timeout_seconds: Annotated[int, Field(ge=1, le=30)] = 15,
) -> dict:
    """Run one explicitly user-authorized VM ROOT shell command via the private tunnel.

    Requires one-time LOCAL owner installation of a root-owned bridge, an
    explicit enabled flag, and precise sudoers permissions for the tunnel OS
    identity. This is unrestricted root: it can alter or destroy anything on
    the VM. Use only for the owner's explicit requested administration, never
    to bypass trading safety gates or retrieve credentials. No execution if
    the privileged bridge is not installed/enabled. No public HTTP route.
    """
    if (type(command) is not str or not command.strip()
            or len(command) > 4096 or "\x00" in command
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 30):
        raise ValueError("Invalid privileged command parameters")
    # Avoid passing exchange/model secrets from the tunnel/dashboard process.
    # Root helper is an immutable, root-owned executable installed locally;
    # there is no dynamic helper path or argument injection.
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/local/sbin/tb2-root-bridge",
             "--timeout", str(timeout_seconds), "--", command],
            input=b"", capture_output=True, check=False, env=env,
            cwd="/", timeout=timeout_seconds + 5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "root_bridge_unavailable_or_timed_out",
            "root_access_active": False,
            "exit_code": None, "output": "",
        }
    if result.returncode != 0 and not result.stdout:
        # Never echo sudo stderr (could include usernames/paths or config).
        return {
            "status": "root_bridge_not_configured_or_rejected",
            "root_access_active": False,
            "exit_code": None, "output": "",
        }
    try:
        reply = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError, TypeError):
        return {
            "status": "root_bridge_invalid_response",
            "root_access_active": False,
            "exit_code": None, "output": "",
        }
    if not isinstance(reply, dict):
        raise ValueError("Invalid privileged bridge response")
    # Only return the helper's fixed schema. The helper truncates/filters
    # output. Do not copy any future untrusted keys into the MCP response.
    status = reply.get("status")
    code = reply.get("exit_code")
    output = reply.get("output")
    if (status not in ("completed", "timed_out", "disabled", "rejected")
            or (code is not None and (type(code) is not int or abs(code) > 255))
            or type(output) is not str or len(output) > 12000):
        raise ValueError("Untrusted privileged bridge response")
    return {
        "status": status,
        "root_access_active": status in ("completed", "timed_out"),
        "exit_code": code,
        "output": output,
        "truncated": reply.get("truncated") is True,
        "command_sha256": reply.get("command_sha256")
            if type(reply.get("command_sha256")) is str
            and len(reply["command_sha256"]) == 64 else None,
    }


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
