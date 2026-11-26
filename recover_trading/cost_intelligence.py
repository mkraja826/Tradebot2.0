"""Read-only exchange fee and model usage accounting; no live policy."""
import argparse
import json
from collections import defaultdict, Counter
from decimal import Decimal
from pathlib import Path
from .performance import dec, stamp, read_performance
from .decision_review import read_review
from .trade_intelligence import sql, obj, mapping, exposure, unique_match, money

VERSION="cost-intelligence-v1"
SYMBOLS=("BTCUSD","XAUTUSD")

def token_usage(result):
    u=mapping(mapping(result.get("diagnostics")).get("usage"))
    a,b,t=(u.get(k) for k in ("prompt_tokens","completion_tokens","total_tokens"))
    if type(a) is not int or type(b) is not int or min(a,b)<0:
        return None
    if t is not None and (type(t) is not int or t!=a+b):
        return None
    return a,b

def price_schedule(raw):
    """Caller-supplied scenario rates, never provider invoice data."""
    if not isinstance(raw,dict):raise ValueError("rate schedule must be an object")
    out={}
    for model,row in raw.items():
        if not isinstance(model,str) or not model or not isinstance(row,dict):raise ValueError("invalid rate")
        cur=row.get("currency")
        a,b=dec(row.get("input_per_million")),dec(row.get("output_per_million"))
        if not isinstance(cur,str) or not cur or a is None or b is None or min(a,b)<0:
            raise ValueError("invalid rate")
        out[model]=(cur,a,b)
    return out

def usage_report(entries, management, rates=None):
    rates=rates or {};groups=defaultdict(lambda:{"statuses":Counter(),"usage_rows":0,"missing_usage_rows":0,
        "input_tokens":0,"output_tokens":0,"estimated_cost":Decimal(0)})
    for dept,rows in (("entry",entries),("management",management)):
        for ident,model,status,created,raw in rows or []:
            if status=="prepared":continue
            g=groups[(dept,model)];g["statuses"][status]+=1
            usage=token_usage(obj(raw))
            if usage is None:g["missing_usage_rows"]+=1;continue
            a,b=usage;g["usage_rows"]+=1;g["input_tokens"]+=a;g["output_tokens"]+=b
            if model in rates:
                _,pa,pb=rates[model];g["estimated_cost"]+=(a*pa+b*pb)/1000000
    out=[]
    for (dept,model),g in sorted(groups.items()):
        rated=model in rates
        out.append({"department":dept,"model":model,"statuses":dict(g["statuses"]),
            "usage_rows":g["usage_rows"],"missing_usage_rows":g["missing_usage_rows"],
            "input_tokens":g["input_tokens"],"output_tokens":g["output_tokens"],
            "estimated_cost_currency":rates[model][0] if rated else None,
            "estimated_reported_token_cost":money(g["estimated_cost"]) if rated and g["usage_rows"] else None,
            "actual_billed_cost":None,
            "usage_coverage_complete":not g["missing_usage_rows"]})
    return {"basis":"journaled_provider_usage_by_reservation_time_not_invoice",
        "entry_journal_available":entries is not None,"management_journal_available":management is not None,
        "groups":out}

def trade_cost(ep, ex):
    gross,fees,net=(dec(ep.get(k)) for k in ("gross_pnl","fees","net_before_funding"))
    notional=dec(ex.get("fill_notional"))
    valid=None not in (gross,fees,net) and gross-fees==net
    return {"decision_id":ep.get("decision_id"),"closed":ep.get("closed"),
        "currency":ex.get("currency"),"status":"reconciled" if valid else "unverified",
        "gross_pnl":money(gross),"exchange_fees":money(fees),"net_before_funding":money(net),
        "reported_funding_raw":ep.get("reported_funding"),"funding_adjusted_net":None,
        "filled_entry_notional":money(notional),
        "round_trip_fee_bps_of_entry_notional":money(fees/notional*10000) if valid and notional is not None and notional>0 else None,
        "fees_exceed_positive_gross":bool(valid and gross>0 and net<0),
        "fee_only_break_even_gross":money(fees) if valid else None,
        "actual_ai_cost":None}

def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        if r["status"]=="reconciled" and r.get("currency"):
            groups[r["currency"]].append(r)
    out=[]
    for cur,rs in sorted(groups.items()):
        gross=sum(dec(r["gross_pnl"]) for r in rs);fees=sum(dec(r["exchange_fees"]) for r in rs)
        net=sum(dec(r["net_before_funding"]) for r in rs)
        out.append({"currency":cur,"episodes":len(rs),"gross_pnl":money(gross),"exchange_fees":money(fees),
            "net_before_funding":money(net),"fees_to_positive_gross_ratio":money(fees/gross) if gross>0 else None,
            "gross_profitable_but_net_losing_count":sum(r["fees_exceed_positive_gross"] for r in rs),
            "funding_reported_count":sum(dec(r["reported_funding_raw"]) is not None for r in rs),
            "average_net_before_funding":money(net/len(rs))})
    return out

def report(root,symbol,start,end,rates=None):
    if symbol not in SYMBOLS or type(start) is not int or type(end) is not int or not 0<=start<end:
        raise ValueError("invalid symbol or UTC epoch interval")
    root=Path(root);p=read_performance(root,symbol);rv=read_review(root,symbol,p)
    decisions=sql(root/"decisions.sqlite","SELECT id,model,status,created,context,result FROM decisions WHERE symbol=?",(symbol,))
    entries=None if decisions is None else [(i,m,s,t,r) for i,m,s,t,c,r in decisions if type(t) is int and start<=t<end]
    mgmt=sql(root/"orders.sqlite","SELECT id,model,status,created,result FROM management_shadow WHERE symbol=? AND created>=? AND created<?",(symbol,start,end))
    rows=[]
    for ep in p.get("recent_episodes",[]):
        if ep.get("attribution")!="single_recover_entry_order":continue
        t=stamp({"created_at":ep.get("closed")})
        if t is None or not start<=t.timestamp()<end:continue
        i=ep.get("decision_id")
        d=unique_match(decisions or [],lambda x:x[0]==i and x[2]=="proposed")
        v=unique_match(rv.get("recent",[]),lambda x:x.get("id")==i and x.get("outcome")=="closed_reconciled"
            and dec(x.get("net_before_funding"))==dec(ep.get("net_before_funding")))
        ex=exposure(obj(d[4]),obj(d[5]),v or {}) if d else {}
        # The episode currency comes from reconciled performance; use no cross-currency conversion.
        ex["currency"]=p.get("currency")
        rows.append(trade_cost(ep,ex))
    expected=mapping(p.get("recover_attributed")).get("closed_episodes")
    available=sum(e.get("attribution")=="single_recover_entry_order" for e in p.get("recent_episodes",[]))
    return {"version":VERSION,"symbol":symbol,"execution_effect":"none","status":p.get("status"),
        "window":{"start_utc_epoch":start,"end_utc_epoch_exclusive":end,
            "trade_basis":"episode_close_time","ai_basis":"journal_reservation_time",
            "full_attributed_history_available":type(expected) is int and expected==available},
        "exchange_costs":summarize(rows),"trades":rows,"ai_usage":usage_report(entries,mgmt,rates),
        "combined_after_all_costs":None,
        "limitations":["AI token estimates require caller-provided scenario rates; actual billed costs remain unknown.",
            "Missing usage, retries outside these journals, Kimi historical charges and other provider costs are not zero.",
            "Episode-close and AI reservation windows are different accounting bases; no combined net is inferred.",
            "Funding sign and completeness require independent exchange ledger verification.",
            "Spread and slippage are reflected in actual fills; do not subtract them a second time.",
            "Recent reconciled episode window is bounded. No live execution or model changes."]}

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",default="/var/lib/recover-trading/demo")
    p.add_argument("--symbol",required=True,choices=SYMBOLS)
    p.add_argument("--start",required=True,type=int);p.add_argument("--end",required=True,type=int)
    p.add_argument("--rates-json",type=Path)
    a=p.parse_args();rates=price_schedule(json.loads(a.rates_json.read_text())) if a.rates_json else {}
    print(json.dumps(report(Path(a.data_dir)/a.symbol,a.symbol,a.start,a.end,rates),allow_nan=False,indent=2))
if __name__=="__main__":main()
