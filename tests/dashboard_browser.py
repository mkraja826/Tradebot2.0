"""Browser regression for mobile inspection, replay, stale data and reconnect."""
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from functools import partial
import time
import os

from playwright.sync_api import sync_playwright

assets = Path(__file__).resolve().parents[1] / "src/tradebot/dashboard_static"
server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(assets)))
Thread(target=server.serve_forever, daemon=True).start()
now = int(time.time())
bucket = now - now % 300
iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
bars = [dict(time=bucket - 300*i, open=100, high=105, low=98, close=103) for i in reversed(range(24))]
isolated = {
    "mode": "read_only", "source": "isolated_child_accounts",
    "checked_at": iso,
    "accounts": {
        label: {
            "status": "connected", "worker_active": True,
            "armed": True, "halted": False, "margin_mode":"isolated_verified",
            "live_position_count": 0, "positions": [], "open_orders": 0,
            "net_equity": "123.45",
            "watchdog_active": True, "equity_collector_active": True,
            "alerts_active": True,
            "fire": {"total": 0, "recent": []},
            "attempts": {"total": 0}, "equity_points": [],
            "equity_health": {"daily_checkpoint": "missed_window",
                              "weekly_checkpoint": "missed_window"},
        }
        for label in ("BTC", "GOLD")
    }
}
snapshot = {
    "live": {"checked_at": iso, "candles": bars, "market": {"status":"fresh","bid":"100","ask":"102"},
             "account":{"status":"connected","btc_open_positions":0,"account_open_orders":0}},
    "events":[{"time":iso,"kind":"ai_decision","details":{"strategy":"WAIT","rationale":"Wide spread"}}],
    "runner":{"status":"running","mode":"observe","age_seconds":2},
}
with sync_playwright() as p:
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    browser = p.chromium.launch(**({"executable_path":executable} if executable else {"channel":"chrome"}))
    for width in (375, 768, 1440):
        page = browser.new_page(viewport={"width":width,"height":844}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.clock.install()
        def slow_snapshot(route):
            time.sleep(0.35)
            route.fulfill(json=snapshot)
        page.route("**/api/overview", slow_snapshot)
        page.route("**/api/isolated/overview",
                   lambda r: r.fulfill(json=isolated))
        page.goto(f"http://127.0.0.1:{server.server_port}/")
        page.get_by_text("BTC + GOLD · ACTIVE",exact=True).wait_for()
        assert page.locator(".isolated-card").count() == 2
        assert page.locator("#isolated-grid").get_by_text("BTCUSD").is_visible()
        assert page.locator("#isolated-grid").get_by_text("XAUTUSD").is_visible()
        page.get_by_text("Bitcoin observer chart and activity", exact=True).click()
        assert page.locator("#mid").inner_text().replace("\n","")=="$101.00"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator("#trace").focus()
        page.keyboard.press("ArrowLeft")
        inspected=page.locator("#inspect-text").inner_text()
        assert "Delta BTCUSD" in inspected
        page.unroute("**/api/overview")
        page.route("**/api/overview", lambda r: r.abort())
        page.clock.fast_forward(10100)
        # Legacy observer outage must not override isolated workers.
        page.get_by_text("Dashboard offline",exact=True).wait_for()
        assert page.locator("#runtime-status").inner_text() == "BTC + GOLD · ACTIVE"
        assert page.locator("#inspect-text").inner_text()==inspected
        page.unroute("**/api/overview")
        page.route("**/api/overview",lambda r:r.fulfill(json=snapshot))
        page.clock.fast_forward(10100)
        page.get_by_text("BTC + GOLD · ACTIVE",exact=True).wait_for()
        assert page.locator("#inspect-text").inner_text()==inspected
        # Separate broker reports fail visibly and recover independently.
        page.unroute("**/api/isolated/overview")
        page.route("**/api/isolated/overview",lambda r:r.abort())
        page.clock.fast_forward(16000)
        page.get_by_text("ACCOUNT DATA CONNECTION LOST",exact=True).wait_for()
        page.unroute("**/api/isolated/overview")
        page.route("**/api/isolated/overview",lambda r:r.fulfill(json=isolated))
        page.clock.fast_forward(16000)
        page.get_by_text("BTC + GOLD · ACTIVE",exact=True).wait_for()
        page.locator("#replay button").first.click()
        page.locator("#context-chat").click()
        assert "Wide spread" in page.locator(".reply").last.inner_text()
        if width<=850:
            page.locator("#chat-close").click()
        page.locator("#dismiss-record").click()
        page.locator("#go-live").click()
        assert page.locator("#inspection").is_hidden()
        assert not errors,errors
        page.close()
    browser.close()
server.shutdown()
