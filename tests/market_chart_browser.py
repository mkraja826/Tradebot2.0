from playwright.sync_api import sync_playwright
from pathlib import Path
import time,json,os
root=Path(__file__).resolve().parents[1]/"src/tradebot/dashboard_static"
now=int(time.time())
reconciliation_fixture={}
def route(r):
    from urllib.parse import urlsplit,parse_qs
    url=urlsplit(r.request.url)
    if not url.path.startswith('/api/'):
        name=url.path[1:] or 'index.html'
        if (root/name).is_file():r.fulfill(path=root/name)
        else:r.fulfill(status=404)
    elif url.path=='/api/chart-desk':
        q=parse_qs(url.query);s=q['symbol'][0];p=q['period'][0];price=3700 if s=='XAUTUSD' else 64000
        step={'5m':300,'1m':60,'15m':900,'1h':3600}[p]
        trade=dict(id='abc',at=now-step*10,orders_submitted=True,direction='LONG',status='flat_verified',decision_at=now-step*9,thesis='Test thesis')
        d=dict(symbol=s,period=p,quote=dict(price=price,mark=price,bid=price-1,ask=price+1,time=now),
               bars=[[now-i*step,price,price+10,price-10,price+1] for i in range(90,0,-1)],trades=[trade],
               account=dict(positions=[dict(size=1,entry_price=price-12,unrealized_pnl=1)],exits=[]))
        if 'trade' in q:
            d['replay']=dict(trade,model_latency_ms=1250,indicators={"session_vwap":3700,"atr_5m":2},scorecard={
                'quote':{'best_bid':price-1,'best_ask':price+1},'moves':{'5':0.12},'exit':None,
                **reconciliation_fixture})
        r.fulfill(json=d)
    elif url.path.startswith('/api/fire'):r.fulfill(json={'execution_enabled':True,'status':'idle','symbol':'XAUTUSD' if 'XAUTUSD' in url.path else 'BTCUSD','indicators':{'as_of':now,'ema_15m':{'close':100,'ema20':99,'slope':'rising'},'atr_5m':2}})
    else:r.fulfill(json={})
with sync_playwright() as pw:
    executable=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE')
    b=pw.chromium.launch(**({'executable_path':executable} if executable else {'channel':'chrome'}))
    page=b.new_page(viewport={'width':390,'height':844},has_touch=True)
    page.route('**/*',route)
    page.goto('http://desk.local/#desk')
    page.wait_for_selector('#desk-positions button')
    page.select_option('#fire-market','XAUTUSD')
    page.wait_for_function("document.querySelector('#desk-price').textContent==='3,700'")
    page.get_by_text('Market at last Fire · XAUTUSD', exact=False).wait_for()
    assert 'Above · rising' in page.locator('#fire-results').inner_text()
    assert 'XAUTUSD' in page.locator('#fire-preview').inner_text()
    page.get_by_role('button',name='15m',exact=True).click()
    page.wait_for_function("document.querySelector('#desk-periods button[aria-pressed=true]').textContent==='15m'")
    page.wait_for_function("document.querySelector('#desk-inspect').textContent.includes('IST')")
    page.locator('#market-canvas').focus()
    page.keyboard.press('ArrowLeft')
    assert 'IST' in page.locator('#desk-inspect').inner_text()
    page.locator('#desk-positions button').first.click()
    page.wait_for_function("document.querySelector('#market-title').textContent.includes('Bitcoin')")
    page.locator('#desk-positions button').last.click()
    page.wait_for_function("document.querySelector('#desk-periods button[aria-pressed=true]').textContent==='15m'")
    page.locator('#desk-history button').first.click()
    page.wait_for_selector('#desk-player:visible')
    page.get_by_text('GPT-6 response · 1.25 s', exact=True).wait_for()
    assert 'Session VWAP / 5m ATR' in page.locator('#desk-scorecard').inner_text()
    assert '5m 0.12%' in page.locator('#desk-scorecard').inner_text()
    assert 'NOT net realized P&L' in page.locator('#desk-scorecard').inner_text()
    assert 'Verified net P&L' not in page.locator('#desk-scorecard').inner_text()
    page.locator('#desk-play').click()
    page.wait_for_timeout(800)
    assert int(page.locator('#desk-scrub').input_value())>0
    page.locator('#desk-live').click()
    page.wait_for_selector('#desk-player',state='hidden')
    reconciliation_fixture.update(is_net_realized_pnl=True,financial_reconciliation_status='broker_reconciled',
        net_realized_pnl_usd='0.075',reconciled_fees_usd='0.1',funding_cashflow_usd='-0.025',
        reconciled_entry_price='3700',reconciled_exit_price='3705',
        entry_fill_count=2,exit_fill_count=2,reconciliation_as_of_us=now*1000000)
    page.locator('#desk-history button').first.click()
    page.get_by_text('Verified net P&L (USD) · 0.075',exact=True).wait_for()
    assert 'Fees / funding cashflow (USD) · 0.1 / -0.025' in page.locator('#desk-scorecard').inner_text()
    assert 'Provisional P&L' not in page.locator('#desk-scorecard').inner_text()
    assert 'Exit · Closed · average fill 3,705' in page.locator('#desk-scorecard').inner_text()
    assert 'No confirmed bracket fill' not in page.locator('#desk-scorecard').inner_text()
    page.locator('#desk-live').click()
    page.wait_for_selector('#desk-player',state='hidden')
    reconciliation_fixture.update(is_net_realized_pnl=False,financial_reconciliation_status='awaiting_complete_broker_evidence',
        net_realized_pnl_usd=None,reconciliation_reason='wallet_funding_mismatch')
    page.locator('#desk-history button').first.click()
    page.get_by_text('Net P&L verification · wallet funding mismatch',exact=True).wait_for()
    assert 'Verified net P&L' not in page.locator('#desk-scorecard').inner_text()
    page.locator('#desk-live').click()
    page.wait_for_selector('#desk-player',state='hidden')
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    print('Mobile chart, market selection, replay and verified/provisional P&L transitions passed')
    b.close()
