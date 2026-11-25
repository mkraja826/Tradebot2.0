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
    expect(page.locator("#marketChart svg")).to_be_visible(timeout=20000)
    page.locator('[data-frame="15m"]').click()
    expect(page.locator("#marketChartTitle")).to_have_text("BTCUSD · 15m")
    expect(page.locator("#marketChart svg")).to_be_visible()
    page.locator(".indicator-settings summary").click()
    page.locator('[data-study="ema9"]').click()
    expect(page.locator('[data-study="ema9"]')).to_have_attribute("aria-pressed","true")
    page.locator("#chartZoomIn").click()
    page.locator("#chartLeft").click()
    page.locator("#chartReset").click()
    page.locator('[data-symbol="XAUTUSD"]').click()
    expect(page.locator("#marketChartTitle")).to_have_text("XAUTUSD · 15m")
    expect(page.locator("#marketChart svg")).to_be_visible()
    page.screenshot(path="browser-artifacts/"+("mobile" if mobile else "desktop")+"-chart.png",full_page=True)
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
