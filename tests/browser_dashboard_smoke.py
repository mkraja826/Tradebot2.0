"""Local browser smoke test using synthetic archive only; no broker/AI requests."""
import json
import sqlite3
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from recover_trading.dashboard import handler, CHART_FRAMES

def seed(root):
    now=int(time.time())
    for index,symbol in enumerate(("BTCUSD","XAUTUSD")):
        d=Path(root)/symbol;d.mkdir()
        (d/"status.json").write_text(json.dumps({"timestamp":now,"status":"fixture","coverage":{"evaluable_rules":0}}))
        with sqlite3.connect(d/"market.sqlite") as db:
            db.execute("CREATE TABLE samples(symbol TEXT,series TEXT,stamp INTEGER,payload TEXT)")
            for frame,step in CHART_FRAMES.items():
                end=(now//step-1)*step
                for i in range(100):
                    t=end-(99-i)*step
                    o=1000*(index+1)+i
                    p={"time":t,"open":o,"high":o+3,"low":o-2,"close":o+1,"volume":i+1}
                    if symbol=="XAUTUSD" and frame=="15m" and i==95:
                        p["high"]=o*2
                        p["low"]=o/2
                    db.execute("INSERT INTO samples VALUES(?,?,?,?)",(symbol,"candle:"+frame,t,json.dumps(p)))

def run(page,url,mobile=False):
    errors=[]
    page.on("pageerror",lambda err:errors.append(str(err)))
    page.goto(url,wait_until="domcontentloaded")
    expect(page.locator("#initialLoad")).to_be_hidden(timeout=20000)
    expect(page.locator("#refresh")).to_contain_text("Updated")
    expect(page.locator('[data-workspace="overview"]')).to_be_visible()
    page.screenshot(path="browser-artifacts/"+("mobile" if mobile else "desktop")+"-overview.png",full_page=True)
    def route(name):
        button=page.locator('[data-page="'+name+'"]')
        if not button.is_visible():
            page.locator("#morePages").click()
        button.click()
        expect(page.locator('[data-workspace="'+name+'"]')).to_be_visible()
        expect(button).to_have_attribute("aria-current","page")
        if mobile:
            # Check hit testing, not only visibility; a covered navigation button is a real failure.
            assert page.evaluate("""() => {const b=document.querySelector('#workspaceNav [data-page="performance"]');const r=b.getBoundingClientRect();return b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"""),"Performance navigation covered on "+name
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"),"Horizontal document overflow on "+name
    route("live")
    expect(page.locator("#chartLiveState")).to_contain_text("unavailable")
    expect(page.locator("#marketChart canvas").first).to_be_visible(timeout=20000)
    page.locator('[data-frame="15m"]').click()
    expect(page.locator("#marketChartTitle")).to_have_text("BTCUSD · 15m")
    expect(page.locator("#marketChart canvas").first).to_be_visible()
    page.locator(".indicator-settings summary").click()
    page.locator("#studyTrend").click()
    expect(page.locator("#indicatorCount")).to_have_text("3 active")
    expect(page.locator('[data-study="ema200"]')).to_have_attribute("aria-pressed","true")
    expect(page.locator("#studyLegend")).to_contain_text("Insufficient contiguous history")
    page.locator("#studyMomentum").click()
    expect(page.locator("#marketChart")).to_have_class("market-chart study-count-2")
    expect(page.locator("#studyLegend")).to_contain_text("MACD 12/26/9")
    page.locator("#studyVolatility").click()
    expect(page.locator("#studyLegend")).to_contain_text("ATR 14")
    page.locator("#studyClear").click()
    expect(page.locator("#indicatorCount")).to_have_text("0 active")
    page.locator('[data-study="ema9"]').click()
    expect(page.locator('[data-study="ema9"]')).to_have_attribute("aria-pressed","true")
    page.locator('[data-study="rsi"]').click()
    expect(page.locator("#marketChart")).to_have_class("market-chart study-count-1")
    expect(page.locator("#marketChartStatus")).to_contain_text("Completed archive")
    page.locator("#chartZoomIn").click()
    page.locator("#chartLeft").click()
    page.locator("#chartReset").click()
    page.locator('[data-symbol="XAUTUSD"]').click()
    expect(page.locator("#marketChartTitle")).to_have_text("XAUTUSD · 15m")
    expect(page.locator("#marketChart canvas").first).to_be_visible()
    expect(page.locator("#chartReference")).to_have_attribute("aria-pressed","true")
    expect(page.locator("#chartLevels")).to_be_disabled()
    expect(page.locator("#chartSourceLabel")).to_contain_text("PRODUCTION MARKET REFERENCE")
    page.locator("#chartDemo").click()
    expect(page.locator("#marketChartStatus")).to_contain_text("Trading archive")
    expect(page.locator("#scaleFocus")).to_have_attribute("aria-pressed","true")
    expect(page.locator("#chartScaleNote")).to_contain_text("raw OHLC unchanged")
    page.locator("#scaleFull").click()
    expect(page.locator("#chartScaleNote")).to_contain_text("Full range")
    page.locator("#scaleLog").click()
    expect(page.locator("#chartScaleNote")).to_contain_text("Logarithmic axis")
    page.locator("#scaleLog").click()
    page.locator("#scaleFocus").click()
    page.locator("#scaleAuto").click()
    expect(page.locator("#chartScaleNote")).to_contain_text("Body focus")
    # Synthetic observed fills, injected through the same dashboard event as overview data.
    page.evaluate("""async () => {const p=await (await fetch("/api/chart?symbol=XAUTUSD&frame=15m")).json();const t=p.candles.at(-3).time;document.dispatchEvent(new CustomEvent("recover:overview",{detail:[{symbol:"XAUTUSD",status:"flat",observed:Math.floor(Date.now()/1000),lines:[],fills:[{id:"fixture-entry",kind:"entry",side:"buy",time:t+10,price:2097.25,size:"2"},{id:"fixture-exit",kind:"exit",side:"sell",time:t+910,price:2099.5,size:"2"}]}]}))}""")
    page.locator("#chartExecutions summary").click()
    expect(page.locator("#chartFillCount")).to_have_text("2 / 2 fills")
    page.locator("#chartFillFilter").select_option("entry")
    expect(page.locator(".chart-fill-row")).to_have_count(1)
    page.locator(".chart-fill-row").click()
    expect(page.locator("#chartFillDetail")).to_contain_text("2,097.25 USD")
    expect(page.locator("#chartFillDetail")).to_contain_text("candle located")
    page.locator("#clearFillSelection").click()
    expect(page.locator("#clearFillSelection")).to_be_disabled()
    page.locator("#chartExecutions summary").click()
    page.screenshot(path="browser-artifacts/"+("mobile" if mobile else "desktop")+"-chart.png",full_page=True)
    page.locator("#marketFullscreen").click()
    expect(page.locator("#marketTerminal")).to_have_attribute("aria-modal","true")
    expect(page.locator("#fullscreenToolbar")).to_be_visible()
    expect(page.locator("#fullscreenScaleTools")).to_be_hidden()
    expect(page.locator("#marketFullscreen")).to_be_focused()
    page.locator("#fullscreenTools").click()
    expect(page.locator("#fullscreenScaleTools")).to_be_visible()
    page.locator("#fullscreenTools").click()
    page.locator('[data-chart-symbol="BTCUSD"]').click()
    expect(page.locator("#marketChartTitle")).to_have_text("BTCUSD · 15m")
    expect(page.locator("#marketChart canvas").first).to_be_visible()
    page.locator('[data-chart-symbol="XAUTUSD"]').click()
    expect(page.locator("#marketChartTitle")).to_have_text("XAUTUSD · 15m")
    expect(page.locator("#marketChart canvas").first).to_be_visible()
    assert page.evaluate("""() => {const r=document.querySelector("#marketTerminal").getBoundingClientRect();return r.x===0&&r.y===0&&Math.abs(r.width-innerWidth)<=1&&Math.abs(r.height-innerHeight)<=2}"""),"Fullscreen does not fill viewport"
    assert page.evaluate("document.querySelector('#marketChart').getBoundingClientRect().height >= 300"),"Chart too short"
    page.screenshot(path="browser-artifacts/"+("mobile" if mobile else "desktop")+"-fullscreen.png")
    page.keyboard.press("Escape")
    expect(page.locator("#marketFullscreen")).to_have_attribute("aria-pressed","false")
    expect(page.locator("#marketFullscreen")).to_be_focused()
    expect(page.locator("#fullscreenToolbar")).to_be_hidden()
    route("history")
    page.locator("#historyQuery").fill("fixture")
    page.locator("#historyReset").click()
    expect(page.locator("#historyQuery")).to_have_value("")
    expect(page.locator("#inspectorEpisode")).to_be_disabled()
    route("intelligence")
    route("strategies")
    route("performance")
    route("learning")
    page.locator("#learnOutcomeFilter").select_option("loss")
    route("health")
    expect(page.locator("#healthMarkets .health-market")).to_have_count(2)
    expect(page.locator("#healthConnection")).to_contain_text("Dashboard snapshot")
    if mobile:
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"),"Horizontal document overflow"
        page.locator("#morePages").click()
        page.keyboard.press("Escape")
        expect(page.locator("#morePages")).to_have_attribute("aria-expanded","false")
    assert not errors,errors

def main():
    Path("browser-artifacts").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        seed(d)
        server=ThreadingHTTPServer(("127.0.0.1",0),handler(d))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                url=f"http://127.0.0.1:{server.server_port}"
                for mobile in (False,True):
                    context=browser.new_context(viewport={"width":390 if mobile else 1440,"height":844 if mobile else 960},has_touch=mobile,is_mobile=mobile,reduced_motion="reduce")
                    context.route("**/*",lambda route:route.continue_() if route.request.url.startswith(url+"/") else route.abort())
                    page=context.new_page()
                    try:run(page,url,mobile)
                    except Exception:
                        page.screenshot(path="browser-artifacts/failure-"+str(mobile)+".png",full_page=True)
                        raise
                    finally:context.close()
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join()
    print("Desktop and mobile browser smoke checks passed.")

if __name__=="__main__":
    main()
