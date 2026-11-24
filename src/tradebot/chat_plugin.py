"""Private stdio MCP adapter for the local Delta demo dashboard."""
import json
import os
import socket
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
    if symbol == "XAUTUSD":
        # Gold autonomous orders belong to a separate signed DEMO child.
        # Never display the parent/mixed-account Gold ledger as its history.
        history = dashboard("/api/isolated/fire/XAUTUSD?page=0")
        overview = dashboard("/api/isolated/overview")
        if (history.get("source") != "gold_isolated_fire_receipts"
                or overview.get("source") != "isolated_child_accounts"):
            raise ValueError("Isolated Gold evidence unavailable")
        account = (overview.get("accounts") or {}).get("GOLD")
        if not isinstance(account, dict):
            raise ValueError("Signed Gold subaccount unavailable")
        rows = history.get("receipts")
        if not isinstance(rows, list):
            raise ValueError("Isolated Gold FIRE history unavailable")
        return {
            "symbol": symbol, "source": "gold_isolated_subaccount",
            "quote": data.get("quote"),
            "positions_and_exits": {"positions": account.get("positions"),
                                    "exits": None},
            "historical_levels": data.get("historical_levels"),
            "latest_fire": rows[0] if rows else None,
            "gold_worker_active": account.get("worker_active"),
            "gold_halted": account.get("halted"),
            "gold_account_status": account.get("status"),
            "history_total": history.get("total"),
            "account_checked_at": overview.get("checked_at"),
        }
    latest = dashboard("/api/fire")
    return {"symbol":symbol,"quote":data.get("quote"),"positions_and_exits":data.get("account"),
            "historical_levels":data.get("historical_levels"),"latest_fire":latest}


@server.tool(annotations=READ)
def fire_history(symbol: Market, page: Annotated[int, Field(ge=0,le=1000000)] = 0) -> dict:
    """List up to 40 historical Fire receipts, newest first, including rejected attempts."""
    if symbol == "XAUTUSD":
        data = dashboard("/api/isolated/fire/XAUTUSD?" + urlencode({"page": page}))
        if data.get("source") != "gold_isolated_fire_receipts":
            raise ValueError("Isolated Gold receipt source unavailable")
        return data
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
    # Classify demo strategy loss warnings independently of raw health evidence.
    # The dashboard checkpoint result is not autonomous execution admission.
    loss_codes = {"equity_daily_loss_limit_breached", "equity_loss_limit_breached"}
    alerts = data.get("alert_codes")
    loss_warnings = sorted({code for code in alerts
                            if isinstance(code, str) and code in loss_codes}) if isinstance(alerts, list) else []
    return {
        "environment": "delta-india-demo",
        "mode": "read_only_checkpoint_health",
        **{name: data.get(name) for name in safe_fields},
        "demo_equity_loss_warnings": loss_warnings,
        "checkpoint_is_execution_admission": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
    }


@server.tool(annotations=READ)
def subaccount_equity_status() -> dict:
    """Read separate BTC and GOLD demo equity diagnostics, never authorize orders."""
    from tradebot.subaccount_equity_report_v3 import account_report
    return account_report(dashboard("/api/isolated/overview"))


@server.tool(annotations=WRITE)
def fire_demo(symbol: Market, fire_id: UUID) -> dict:
    """Request one GPT-decided demo trade. Generate a UUID for this explicit request and retain it.
    Reuse the same symbol and ID after interruptions. Acceptance only reserves the request."""
    return dashboard(f"/api/plugin/fire/{symbol}/{fire_id.hex}", submit=True)


@server.tool(annotations=READ)
def review_fire(symbol: Market, fire_id: UUID) -> dict:
    """Look up an exact Fire ID. Read its saved thesis, indicators, broker fill evidence and scorecard.
    A missing confirmed exit or net P&L means unknown. Compare trades by looking up both IDs."""
    if symbol == "XAUTUSD":
        report = dashboard(f"/api/isolated/review/XAUTUSD/{fire_id.hex}")
        if report.get("source") != "gold_isolated_fire_receipts":
            raise ValueError("Isolated Gold trade evidence unavailable")
        return report
    return dashboard(f"/api/plugin/review/{symbol}/{fire_id.hex}")


@server.tool(annotations=ROOT_WRITE)
def admin_root_shell(
    command: Annotated[str, Field(min_length=1, max_length=4096)],
    timeout_seconds: Annotated[int, Field(ge=1, le=30)] = 15,
) -> dict:
    """Run one explicitly user-authorized VM ROOT shell command via the private tunnel.

    Requires one-time LOCAL owner installation of the root-owned socket
    adapter and bridge, with explicit local enablement and peer-credential
    verification. This is unrestricted root: it can alter or destroy anything on
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
    # Use a root-owned local socket; tunnel NoNewPrivs prevents sudo elevation.
    # Root socket verifies kernel SO_PEERCRED and invokes the existing audited bridge.
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            channel.settimeout(timeout_seconds + 7)
            channel.connect('/run/tb2-root-admin.sock')
            request = json.dumps({"command": command, "timeout_seconds": timeout_seconds})
            channel.sendall(request.encode("utf-8") + b"\n")
            chunks = bytearray()
            while b"\n" not in chunks:
                block = channel.recv(4096)
                if not block:
                    break
                chunks.extend(block)
                if len(chunks) > 16384:
                    raise ValueError("Oversized root bridge reply")
        reply = json.loads(bytes(chunks).split(b"\n", 1)[0])
    except (OSError, TimeoutError, ValueError, UnicodeError, IndexError):
        return {
            "status": "root_socket_unavailable_or_rejected",
            "root_access_active": False,
            "exit_code": None,
            "output": "",
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
