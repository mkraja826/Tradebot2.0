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
performance = {
    "mode": "read_only", "source": "isolated_signed_broker_performance",
    "checked_at": iso, "window_days": 7,
    "accounts": {
        label: {
            "status":"complete_broker_window", "as_of":iso,
            "signed_fill_count":4, "signed_wallet_posting_count":5,
            "broker_reconciled_closed_trades":0,
            "unverified_or_open_trades":1, "verified_subset_net_usd":None,
            "verified_subset_win_rate_pct":None,
            "trade_rows":[{
                "time":iso,"status":"flat_verified","direction":"LONG",
                "contracts":2,"is_net_realized_pnl":False,
                "reconciliation_status":"unverified",
                "reason":"missing_broker_funding_total"}],
            "wallet":{
                "last_24h":{"status":"verified_posted_cashflow",
                    "posted_net_usd":"2.25", "gross_cashflow_usd":"3.00",
                    "fees_usd":"-0.75","funding_usd":"0"},
                "last_7d":{"status":"verified_posted_cashflow",
                    "posted_net_usd":"14.25", "gross_cashflow_usd":"16.00",
                    "fees_usd":"-1.75","funding_usd":"0"}
            }
        } for label in ("BTC","GOLD")
    }
}
snapshot = {
    "live": {"checked_at": iso, "candles": bars, "market": {"status":"fresh","bid":"100","ask":"102"},
             "account":{"status":"connected","btc_open_positions":0,"account_open_orders":0}},
    "events":[
      *[{"time":iso,"kind":"ai_decision",
          "details":{"strategy":"WAIT","rationale":"Wide spread"}} for _ in range(7)],
      *[{"time":iso,"kind":"ai_response_rejected",
          "details":{"reason":"completion_limit"}} for _ in range(3)],
    ],
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
        page.route("**/api/isolated/performance",
                   lambda r: r.fulfill(json=performance))
        page.goto(f"http://127.0.0.1:{server.server_port}/")
        page.get_by_text("BTC + GOLD · ACTIVE",exact=True).wait_for()
        assert page.locator("body").get_attribute("data-screen") == "home"
        page.get_by_text("Your trading desk",exact=True).wait_for()
        assert page.locator("#home-equity").inner_text() == "$246.90"
        assert page.locator("#home-service-count").inner_text() == "8/8"
        assert page.locator("#home-bots-running").inner_text() == "2/2"
        assert page.locator("#home-equity-graph polyline").count()==0  # no invented trend
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        menu = ".dock" if width <= 850 else ".sidebar"
        def switch(screen):
            page.locator(menu).locator('a[data-workspace-link="' + screen + '"]').click()
            assert page.locator("body").get_attribute("data-screen") == screen
        switch("bots")
        assert page.locator(".isolated-card").count() == 2
        assert page.locator("#isolated-grid").get_by_text("BTCUSD").is_visible()
        assert page.locator("#isolated-grid").get_by_text("XAUTUSD").is_visible()
        switch("analytics")
        page.locator("#performance-grid .performance-card").first.get_by_text("$2.25").wait_for()
        assert page.locator("#performance-grid .perf-unverified").count()==2
        assert page.locator("#performance-grid .perf-verified").count()==0
        page.locator("#performance-7d").click()
        assert page.locator("#performance-7d").get_attribute("aria-pressed")=="true"
        assert page.locator("#performance-grid .performance-card").first.get_by_text("$14.25").is_visible()
        page.locator("#performance-24h").click()
        switch("activity")
        page.get_by_text("7 similar WAIT observations",exact=True).wait_for()
        page.get_by_text("3 AI responses hit the completion limit",exact=True).wait_for()
        assert page.locator("#events > details.activity-group").count()==2
        page.locator("#events > details.activity-group").first.locator("summary").click()
        assert page.locator("#events > details.activity-group").first.locator(".event").count()==7
        switch("desk")
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
        # The old refresh-label is CSS-hidden at 375px; inspect its text,
        # not visibility, while testing observer disconnect handling.
        page.wait_for_function(
            'document.getElementById("refresh-label").textContent === "Dashboard offline"')
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
