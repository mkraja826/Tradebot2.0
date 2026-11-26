"""Bounded prior evidence and current geometry for opt-in demo AI context.

No broker calls, extra AI calls, trading thresholds or automatic policy promotion.
"""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from collections import Counter
from .performance import dec,stamp
from .regime import FAMILIES

VERSION="research-context-v1"
MARKETS={"BTCUSD":"B","XAUTUSD":"G"}
PROMPT="Optional research_evidence contains historical observations and descriptive current geometry only. Consider net costs, monetary stop exposure, contrary signals and the rationale for retaining exposure. Past outcomes do not establish present direction, probability, causal benefit, or a mandatory rule. Missing evidence is unknown. Use current executable quote and mark separately; preserve the existing proposal schema and decision discretion."

def mapping(v):return v if isinstance(v,dict) else {}
def money(v):return str(v) if v is not None else None
def positive(v):
    d=dec(v);return d if d is not None and d>0 else None

def prior(path,symbol,cutoff):
    out={"version":VERSION,"symbol":symbol,"as_of":cutoff,"status":"unavailable","samples":0,
         "validated_lessons":[],"causal_validation":False}
    if path is None or symbol not in MARKETS or type(cutoff) is not int or cutoff<=0:return out
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=.15)) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute("SELECT decision_id,closed,enrolled,payload FROM lessons WHERE symbol=? AND enrolled<? ORDER BY enrolled DESC,decision_id LIMIT 32",(symbol,cutoff)).fetchall()
    except (sqlite3.Error,OSError,ValueError,TypeError):return out
    valid=[];seen=set()
    for ident,closed,enrolled,raw in rows:
        try:
            d=json.loads(raw);end=stamp({"created_at":closed});op=stamp({"created_at":d.get("opened")})
            g,f,n=map(dec,(d.get("gross_pnl"),d.get("fees"),d.get("net_before_funding")))
            if (d.get("symbol")!=symbol or d.get("decision_id")!=ident or d.get("closed")!=closed
                or d.get("learning_status")!="observation_only" or d.get("execution_effect")!="none"
                or d.get("direction") not in ("LONG","SHORT") or op is None or end is None
                or not op<end or type(enrolled) is not int or not end.timestamp()<=enrolled<cutoff
                or None in (g,f,n) or g-f!=n or any(abs(v)>1000000000 for v in (g,f,n))
                or (ident,closed) in seen):continue
            seen.add((ident,closed));x=mapping(d.get("exit_evidence"))
            mfe,mae=dec(x.get("mfe_bps")),dec(x.get("mae_bps"))
            full=x.get("status")=="complete_interior_lower_bound" and None not in (mfe,mae) and 0<=min(mfe,mae)<=max(mfe,mae)<1000
            valid.append((g,f,n,full,mfe))
            if len(valid)==12:break
        except (ValueError,TypeError,AttributeError,ArithmeticError,OverflowError):continue
    out.update(status="observed" if valid else "no_prior_evidence",samples=len(valid))
    if valid:
        g=sum(v[0] for v in valid);f=sum(v[1] for v in valid);n=sum(v[2] for v in valid)
        out.update(gross_pnl=money(g),exchange_fees=money(f),net_before_funding=money(n),
                   net_wins=sum(v[2]>0 for v in valid),gross_positive_net_loss=sum(v[0]>0>v[2] for v in valid),
                   full_excursion_samples=sum(v[3] for v in valid),
                   losses_low_favorable_movement=sum(v[2]<0 and v[3] and v[4]<10 for v in valid),
                   losses_after_favorable_movement=sum(v[2]<0 and v[3] and v[4]>=25 for v in valid))
    return out

def current(context):
    symbol=context.get("symbol");direction=mapping(context.get("direction_engine"))
    side=direction.get("direction")
    fam=mapping(direction.get("family_scores"))
    support=sorted(k for k,v in fam.items() if isinstance(k,str) and k in set(FAMILIES.values()) and side in ("LONG","SHORT") and side in mapping(v))
    opposite="SHORT" if side=="LONG" else "LONG" if side=="SHORT" else None
    against=sorted(k for k,v in fam.items() if isinstance(k,str) and k in set(FAMILIES.values()) and opposite and opposite in mapping(v))
    result={"direction":side if side in ("LONG","SHORT","NEUTRAL") else None,
            "supporting_families":support,"opposing_families":against,
            "shared_families":sorted(set(support)&set(against))}
    if "position" in context:
        e=mapping(context.get("exit_geometry"))
        result["position_geometry"]={k:money(dec(e.get(k))) for k in ("current_gross_mark_return_bps","mark_to_stop_bps","mark_to_target_bps","remaining_target_to_stop_distance_ratio")}
        return result
    a=mapping(context.get("demo_account"));p=mapping(a.get("product"));q=mapping(a.get("decision_quote"))
    bid,ask=positive(q.get("best_bid")),positive(q.get("best_ask"))
    price=ask if side=="LONG" else bid if side=="SHORT" else None
    quote_ok=q.get("status")=="fresh_book" and None not in (bid,ask) and bid<=ask
    result["decision_quote"]={"status":"recorded_fresh_book" if quote_ok else "unavailable",
        "spread_bps":money((ask-bid)/((ask+bid)/2)*10000) if quote_ok else None}
    cv=positive(p.get("contract_value"));currency=mapping(p.get("settling_asset")).get("symbol")
    if (quote_ok and price is not None and cv is not None and p.get("symbol")==symbol
        and p.get("notional_type")=="vanilla" and currency and currency==mapping(p.get("quoting_asset")).get("symbol")
        and dec(a.get("leverage"))==20):
        result["linear_exposure_per_contract"]={"currency":currency,"reference":money(price),"notional":money(price*cv),
            "estimated_initial_margin_excluding_fees":money(price*cv/20),
            "monetary_change_per_1pct_price_move":money(price*cv/100),
            "basis":"quote_based_estimate_not_exchange_margin"}
    return result

def attach_context(context,evidence):
    if (not isinstance(evidence,dict) or evidence.get("version")!=VERSION
        or evidence.get("symbol")!=context.get("symbol") or evidence.get("as_of")!=context.get("as_of")):
        return context
    try:
        return {**context,"research_evidence":{"version":VERSION,"as_of":context["as_of"],
            "historical":evidence,"current":current(context),
            "policy":"descriptive context only, not a trading rule"}}
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError):return context

def replay(root,symbol,learning_path,limit=10):
    """Archived contexts only; compare payload coverage/size without provider calls."""
    if symbol not in MARKETS or type(limit) is not int or not 1<=limit<=20:raise ValueError("invalid replay scope")
    out={"symbol":symbol,"execution_effect":"none","provider_calls":0,"rows":[]}
    for dept,file,table in (("entry","decisions.sqlite","decisions"),("management","orders.sqlite","management_shadow")):
        try:
            with closing(sqlite3.connect((Path(root)/file).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
                rows=db.execute(f"SELECT id,context FROM {table} WHERE symbol=? AND status='proposed' ORDER BY created DESC LIMIT ?",(symbol,limit)).fetchall()
        except sqlite3.Error:continue
        for ident,raw in rows:
            try:
                c=json.loads(raw)
                if c.get("symbol")!=symbol:continue
                at=c["as_of"];ev=prior(learning_path,symbol,at);candidate=attach_context(c,ev)
                out["rows"].append({"department":dept,"id":ident,"as_of":at,
                    "added_bytes":len(json.dumps(candidate,allow_nan=False).encode())-len(json.dumps(c,allow_nan=False).encode()),
                    "prior_samples":ev["samples"],"current_evidence":list(mapping(mapping(candidate.get("research_evidence")).get("current")).keys())})
            except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError):continue
    out["status"]="context_comparison_only" if out["rows"] else "no_data"
    out["candidate_policy_tested"]=False
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",required=True,type=Path);p.add_argument("--learning-journal",required=True,type=Path)
    p.add_argument("--symbol",required=True,choices=tuple(MARKETS));p.add_argument("--limit",type=int,default=10)
    a=p.parse_args();print(json.dumps(replay(a.data_dir/a.symbol,a.symbol,a.learning_journal,a.limit),indent=2,allow_nan=False))
if __name__=="__main__":main()
