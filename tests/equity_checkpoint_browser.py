"""Offline mobile safety-banner regression; no broker or AI calls."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1] / "src/tradebot/dashboard_static"
fixture = {}
requests = []


def report(**changes):
    return {
        "mode":"read_only", "trade_authorized":False, "source":"delta_demo_signed_wallet",
        "as_of":datetime.now(timezone.utc).isoformat(), "status":"healthy",
        "daily_checkpoint":"verified", "weekly_checkpoint":"verified",
        "checkpoint_prerequisites_met":True, "observation_status":"fresh",
        "latest_observation_age_seconds":1,
        "monitoring":{"watchdog":"healthy", "equity_collector":"healthy"}, **changes,
    }


def route(r):
    from urllib.parse import urlsplit
    path = urlsplit(r.request.url).path
    requests.append((r.request.method, path))
    if path == "/api/risk/checkpoints":
        if fixture is None:
            r.abort()
        else:
            r.fulfill(json=fixture)
    elif path.startswith("/api/"):
        r.fulfill(json={"execution_enabled":False, "status":"idle"})
    else:
        asset = root / (path.lstrip("/") or "index.html")
        r.fulfill(path=asset) if asset.is_file() else r.fulfill(status=404)


with sync_playwright() as pw:
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    browser = pw.chromium.launch(**({"executable_path":executable} if executable else {"channel":"chrome"}))
    for width in (375, 768, 1440):
        errors = []
        page = browser.new_page(viewport={"width":width,"height":844}, reduced_motion="reduce")
        page.on("pageerror", lambda e:errors.append(str(e)))
        page.route("**/*", route)
        fixture = report()
        page.goto("http://equity.local/#desk")
        banner = page.locator("#equity-risk-banner")
        page.wait_for_function("document.querySelector('#equity-risk-banner').dataset.state==='healthy'")
        assert "does not authorize a trade" in banner.inner_text()
        assert "Watchdog: Reporting" in banner.inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for status, daily, weekly in (("checkpoint_pending","pending_window","pending_window"),
                                     ("checkpoint_missed","missed_window","missed_window"),
                                     ("evidence_stale","verified","verified"),
                                     ("monitoring_degraded","verified","verified")):
            fixture = report(status=status,daily_checkpoint=daily,weekly_checkpoint=weekly,
                             checkpoint_prerequisites_met=False,latest_observation_age_seconds=240,
                             monitoring={"watchdog":"stale","equity_collector":"broker_authentication_failed"})
            page.evaluate("refreshEquityCheckpointRisk()")
            assert banner.get_attribute("data-state") == status
            assert "READ ONLY · VERIFIED" not in banner.inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        # A stale success, contradictory success, malformed response, injection
        # or connection failure must never leave the previous green state behind.
        for fixture in (
            report(as_of=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()),
            report(daily_checkpoint="missed_window"), report(trade_authorized=True),
            report(monitoring={"watchdog":"<script>throw 1</script>","equity_collector":"healthy"}),
            {"status":"healthy"}, None,
        ):
            page.evaluate("refreshEquityCheckpointRisk()")
            assert banner.get_attribute("data-state") == "evidence_unavailable"
        fixture = report()
        page.evaluate("refreshEquityCheckpointRisk()")
        assert banner.get_attribute("data-state") == "healthy"
        assert not errors, errors
        page.close()
    browser.close()
assert all(method == "GET" for method, _ in requests), requests
print("Equity checkpoint banner passed at 375, 768 and 1440 px; GET-only, stale and failure states verified.")
