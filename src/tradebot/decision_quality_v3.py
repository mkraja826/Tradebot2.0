"""Offline proposal diagnostics. No model judgement, account sizing authority or broker calls."""
from decimal import Decimal
from tradebot.ai_decision_v3 import validate
from tradebot.opportunity_journal_v3 import digest,ROUTE,known_route
from tradebot.market_data_v3 import normalize
from tradebot.advanced_backtest_v3 import COSTS

def assess(q,a,product=None,*,decision_at):
    p=q["payload"]; s=p["symbol"]
    if q.get("execution_authorized") is not False or q["request_sha256"]!=digest(p) or not known_route(s,q["model_if_enabled"]):
        raise ValueError("invalid_request")
    if type(decision_at) is not int or not 0<=decision_at-p["as_of"]<=150: raise ValueError("invalid_decision_time")
    validate(a,q)
    action=a["action"]
    out={"action":action,"contract_valid":True,"source":"synthetic_fixture","model_quality":None,
         "execution_authorized":False,"signal_alignment":None,"proposal":None}
    if action=="WAIT": return out
    sides={x["direction"] for x in p["new_signals"]}
    out["signal_alignment"]="mixed" if len(sides)>1 else "aligned" if action in sides else "opposite"
    plan=a["plan"]; e,sl,tp=map(lambda k:Decimal(str(plan[k])),("entry_reference","stop_loss","take_profit"))
    risk=abs(e-sl); reward=abs(tp-e)
    d={"stop_distance_pct":float(100*risk/e),"target_distance_pct":float(100*reward/e),
       "reward_risk_ratio":float(reward/risk),"product_status":"unavailable","notional_usd":None,
       "simple_initial_margin_usd":None,"margin_difference_usd":None,"price_tick_aligned":None,
       "broker_margin_verified":False,"leverage_limit_verified":False}
    if product and product.get("symbol")==s and product.get("source")=="delta_demo_public_product" and product.get("quote_currency")==product.get("settlement_currency")=="USD" and 0<=decision_at-product["observed_at"]<=300:
        tick=Decimal(product["tick_size"]); unit=Decimal(product["contract_value"])
        if tick.is_finite() and unit.is_finite() and min(tick,unit)>0:
            n=e*unit*plan["contracts"]; m=n/Decimal(str(plan["leverage"]))
            d.update(product_status="reference_only",notional_usd=float(n),simple_initial_margin_usd=float(m),
                margin_difference_usd=float(Decimal(str(plan["margin_quote"]))-m),
                price_tick_aligned=all(x%tick==0 for x in (e,sl,tp)))
    out["proposal"]=d
    return out

def outcome(q,a,read_bars,*,decision_at,now):
    assess(q,a,decision_at=decision_at)
    if a["action"]=="WAIT": return {"status":"not_applicable_wait"}
    p=a["plan"]; h=p["holding_minutes"]
    if p["entry_type"]!="MARKET": return {"status":"limit_fill_not_modelled"}
    if h not in range(5,241,5): return {"status":"unsupported_horizon"}
    start=(decision_at//300+1)*300; end=start+h*60
    if end>now: return {"status":"pending","reference_start":start,"reference_end":end}
    try: bars=normalize(read_bars(a["symbol"],start,end),"5m",as_of=end,count=h//5)
    except ValueError: return {"status":"missing_candles"}
    e=bars[0]["open"]; sl=p["stop_loss"]; tp=p["take_profit"]; sign=1 if a["action"]=="LONG" else -1
    if not (sl<e<tp if sign==1 else tp<e<sl): return {"status":"entry_gap_outside_bracket"}
    exit=bars[-1]["close"]; reason="time_exit"; ambiguous=False
    for b in bars:
        o,hi,lo=(b[k] for k in ("open","high","low"))
        if (o<=sl if sign==1 else o>=sl): exit=o; reason="stop_gap"; break
        if (o>=tp if sign==1 else o<=tp): exit=tp; reason="target_gap"; break
        stop=lo<=sl if sign==1 else hi>=sl; target=hi>=tp if sign==1 else lo<=tp
        if stop: exit=sl;reason="stop";ambiguous=target;break
        if target: exit=tp;reason="target";break
    gross=100*sign*(exit/e-1)
    return {"status":"hypothetical_observed","reference_start":start,"reference_end":end,"entry_reference_open":e,
        "exit_reference":exit,"exit_reason":reason,"ambiguous_bar_stop_first":ambiguous,
        "entry_adverse_drift_pct":100*sign*(e/p["entry_reference"]-1),"gross_pct":gross,
        "cost_scenarios_pct":{str(c):gross-c/100 for c in COSTS},"actual_fill_verified":False}


def report(root,*,now):
    import json,sqlite3
    from pathlib import Path
    from contextlib import closing
    from collections import Counter
    from tradebot.ai_decision_v3 import prepare
    from tradebot.research_collector_v3 import atomic_json
    root=Path(root)
    out={"mode":"synthetic_decision_quality","checked_at":now,"markets":{},"execution_authorized":False,"paid_ai_requests":0,"orders_submitted":0,"model_quality":None}
    def ro(name):
        p=root/name
        if p.is_symlink() or not p.is_file(): raise ValueError("untrusted_database")
        return sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    with closing(ro("shadow-decisions-v3.sqlite")) as decisions,closing(ro("opportunities-v3.sqlite")) as events:
        for s in ROUTE:
            counts=Counter(); rows=decisions.execute("select event_id,payload from decisions where symbol=? order by rowid desc limit 501",(s,)).fetchall()
            for event_id,raw in rows[:500]:
                counts["records"]+=1
                try:
                    r=json.loads(raw)
                    e=events.execute("select payload from events where event_id=? and symbol=?",(event_id,s)).fetchone()
                    if not e: raise ValueError("missing_event")
                    q=prepare(json.loads(e[0])); a=r["response"]
                    if r["mode"]!="synthetic_wait_only" or r["execution_authorized"] is not False or r["request_sha256"]!=q["request_sha256"] or r["response_sha256"]!=digest(a) or a["action"]!="WAIT": raise ValueError("invalid_receipt")
                    validate(a,q); counts["valid"]+=1; counts["synthetic_wait"]+=1
                    if q["payload"]["context"].get("strategy_learning",{}).get("status")=="research_advisory": counts["learning_enriched"]+=1
                except (ValueError,KeyError,TypeError,AttributeError): counts["invalid"]+=1
            out["markets"][s]={**{k:counts[k] for k in ("records","valid","invalid","synthetic_wait","learning_enriched")},"truncated":len(rows)>500,"actual_model_decisions_verified":0,"model_quality":None,"directional_outcomes":"no_actual_model_evidence"}
    atomic_json(root/"decision-quality-v3.json",out)
    return out
