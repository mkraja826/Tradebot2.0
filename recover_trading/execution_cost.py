"""Read-only measured commission and quote-cost evidence. No order or model calls."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from decimal import Decimal
from statistics import median
from .performance import dec,stamp
VERSION="execution-cost-v1"

def product_identity(p):
    return (p.get("id"),p.get("symbol"),p.get("contract_value"),p.get("notional_type"),(p.get("settling_asset") or {}).get("symbol"),(p.get("quoting_asset") or {}).get("symbol"))

def fees(fills,spec,symbol):
    value=dec(spec.get("contract_value"));pid,_,_,kind,currency,quote=product_identity(spec)
    out={"status":"unsupported_product","samples":0,"excluded":len(fills)}
    if spec.get("symbol")!=symbol or pid is None or not currency or currency!=quote or kind!="vanilla" or value is None or value<=0:return out
    total=Decimal(0);notional=Decimal(0);rates=[];seen=set()
    for f in fills:
        i=f.get("id");q,p,c=(dec(f.get(k)) for k in ("size","price","commission"))
        if i is None or i in seen or f.get("product_symbol")!=symbol or str(f.get("product_id"))!=str(pid) or f.get("settling_asset_symbol")!=currency or stamp(f) is None or q is None or p is None or c is None or min(q,p)<=0:continue
        seen.add(i);n=q*p*value;notional+=n;total+=c;rates.append(float(c/n*10000))
    out.update(status="observed_subset",currency=currency,samples=len(rates),excluded=len(fills)-len(rates),observed_turnover=str(notional),observed_commission=str(total),
        turnover_weighted_one_way_fee_bps=float(total/notional*10000) if notional else None,median_fill_fee_bps=median(rates) if rates else None)
    return out

def closed_cost(s):
    g,c,n=(dec(s.get(k)) for k in ("gross_pnl","fees","net_before_funding"))
    return {"closed_episodes":s.get("closed_episodes"),"gross_pnl":s.get("gross_pnl"),"commission":s.get("fees"),"net_before_funding":s.get("net_before_funding"),
        "commission_pct_of_positive_aggregate_gross":float(c/g*100) if g is not None and g>0 and c is not None and n==g-c else None}

def spread_sample(rows,now):
    values=[];buckets=set()
    for t,r in sorted(rows,key=lambda x:x[0]):
        if type(t) is not int or r.get("timestamp_us")!=t or not (now-3600)*1000000<=t<=now*1000000:continue
        bid,ask=(dec(r.get(k)) for k in ("bid","ask"))
        if bid is None or ask is None or not 0<bid<=ask:continue
        bucket=t//60000000
        if bucket in buckets:continue
        buckets.add(bucket);values.append(float((ask-bid)/((ask+bid)/2)*10000))
    return {"window_s":3600,"samples":len(values),"median_full_spread_bps":median(values) if values else None,"maximum_full_spread_bps":max(values) if values else None,
        "basis":"first_valid_archived_ticker_per_minute_not_trade_time_spread"}

def build(symbol,performance,review,fills,spec,tickers,now):
    episodes=performance.get("recent_episodes",[])
    funding=[dec(e.get("reported_funding")) for e in episodes]
    attributed=[e for e in episodes if e.get("decision_id")]
    entries=[]
    for r in review.get("recent",[]):
        if r.get("filled_contracts") is None:continue
        evidence=r.get("entry_quote_evidence") or {};a=r.get("entry_attribution") or {}
        def spread(k):
            q=evidence.get(k) or {}
            v=dec(q.get("spread_bps"))
            return float(v) if q.get("status")=="fresh_book" and v is not None and v>=0 else None
        entries.append({"decision_id":r["id"],"outcome":r.get("outcome"),"reference_deviation_bps":r.get("entry_deviation_bps"),
            "decision_full_spread_bps":spread("decision_quote"),"submission_full_spread_bps":spread("pre_submit_quote"),
            "submission_book_to_fill_bps":a.get("submission_book_to_fill_bps"),"complete_decomposition":a.get("complete_decomposition") is True})
    return {"version":VERSION,"symbol":symbol,"status":"observed","execution_effect":"none","currency":performance.get("currency"),
        "fill_commission":fees(fills,spec,symbol),"all_reconciled":closed_cost(performance.get("all_reconciled") or {}),
        "recover_attributed":closed_cost(performance.get("recover_attributed") or {}),"unattributed":closed_cost(performance.get("unattributed") or {}),
        "funding":{"recent_closed_episodes":len(episodes),"reported_field_present":sum(x is not None for x in funding),"missing_field":sum(x is None for x in funding),
            "recover_recent_episodes":len(attributed),"recover_reported_field_present":sum(dec(e.get("reported_funding")) is not None for e in attributed),
            "signed_total":None,"status":"ledger_reconciliation_not_available"},
        "spread":spread_sample(tickers,now),"entry_samples":entries,
        "limitations":["Observed fill commission includes historical, open and unattributed trades; closed totals are separate. Fee rate is per one-way turnover, not round-trip.",
        "Funding field presence does not establish signed cash settlement; no missing value assumed zero or combined into net.",
        "Full quoted spread is an indicative market observation, not realized execution cost. Entry reference deviation is not necessarily slippage.",
        "Do not add spread or reference deviation to realized P&L, which already uses actual fill prices. No estimated funding or automatic trading changes."]}

def report(root,symbol,performance,review,now):
    root=Path(root)
    def connect(name):return sqlite3.connect((root/name).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)
    try:
        with closing(connect("decisions.sqlite")) as db:
            specs=[p for r, in db.execute("SELECT context FROM decisions WHERE symbol=?",(symbol,)) if (p:=json.loads(r).get("demo_account",{}).get("product"))]
        spec=specs[0] if specs and all(product_identity(p)==product_identity(specs[0]) for p in specs) else {}
        with closing(connect("orders.sqlite")) as db:
            fills=[json.loads(r) for r, in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))]
        with closing(connect("market.sqlite")) as db:
            tickers=[(t,json.loads(r)) for t,r in db.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series='ticker' AND stamp>=? AND stamp<=?",(symbol,(now-3600)*1000000,now*1000000))]
        return build(symbol,performance,review,fills,spec,tickers,now)
    except (sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,ArithmeticError):
        return {"version":VERSION,"symbol":symbol,"status":"unavailable","execution_effect":"none"}
