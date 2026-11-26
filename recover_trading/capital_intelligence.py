"""Offline capital allocation diagnostics. No order, provider or sizing policy changes."""
import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from .performance import dec, read_performance
from .decision_review import read_review
from .trade_intelligence import sql, obj, mapping, exposure, unique_match, money

VERSION="capital-intelligence-v1"
SYMBOLS=("BTCUSD","XAUTUSD")

def ratio(a,b):
    return money(a/b) if a is not None and b is not None and b>0 else None

def positive(x):
    v=dec(x)
    return v if v is not None and v>0 else None

def allocation(context,result,review,episode):
    account=mapping(context.get("demo_account"))
    spec=mapping(account.get("product"))
    currency=mapping(spec.get("settling_asset")).get("symbol")
    wallets=account.get("wallets")
    matches=[w for w in wallets if isinstance(w,dict) and currency and w.get("asset_symbol")==currency] if isinstance(wallets,list) else []
    wallet=matches[0] if len(matches)==1 else {}
    balance=positive(wallet.get("balance"));available=dec(wallet.get("available_balance"))
    if available is not None and available<0:available=None
    ex=exposure(context,result,review)
    planned=positive(result.get("capital_allocation"))
    estimated=positive(ex.get("estimated_initial_margin_excluding_fees"))
    notional=positive(ex.get("fill_notional"))
    risk=positive(ex.get("planned_stop_loss_amount_at_fill"))
    target=positive(ex.get("planned_target_gain_at_fill"))
    net=dec(episode.get("net_before_funding"));fees=dec(episode.get("fees"))
    qty=positive(result.get("size"));filled=positive(ex.get("filled_contracts"))
    price=positive(result.get("entry_reference"));cv=positive(spec.get("contract_value"))
    lev=positive(result.get("leverage"))
    quote_currency=mapping(spec.get("quoting_asset")).get("symbol")
    compatible=(spec.get("notional_type")=="vanilla" and bool(currency) and currency==quote_currency
                and context.get("symbol")==spec.get("symbol")==result.get("symbol") and lev==20)
    proposed_notional=qty*price*cv if compatible and None not in (qty,price,cv) else None
    proposed_margin=proposed_notional/lev if proposed_notional is not None else None
    # Do not normalize unsupported contract models or currencies.
    if not compatible:
        estimated=notional=risk=target=None
    out={"currency":currency,"wallet_status":"observed_unique_settlement_wallet" if len(matches)==1 else "missing_or_ambiguous",
        "wallet_balance_at_decision":money(balance),"wallet_available_at_decision":money(available),
        "position_margin_at_decision":money(dec(wallet.get("position_margin"))),
        "order_margin_at_decision":money(dec(wallet.get("order_margin"))),
        "planned_capital_allocation":money(planned),"planned_contracts":money(qty),"filled_contracts":money(filled),
        "planned_notional_at_reference":money(proposed_notional),"planned_initial_margin_estimate":money(proposed_margin),
        "filled_notional":money(notional),"filled_initial_margin_estimate":money(estimated),
        "planned_loss_at_actual_fill":money(risk),"planned_target_gain_at_actual_fill":money(target),
        "planned_margin_to_available":ratio(planned,available),
        "estimated_filled_margin_to_available":ratio(estimated,available),
        "estimated_stop_loss_to_wallet_balance":ratio(risk,balance),
        "estimated_stop_loss_to_available":ratio(risk,available),
        "estimated_margin_to_planned_budget":ratio(estimated,planned),
        "filled_to_planned_contracts":ratio(filled,qty),
        "observed_net_to_estimated_margin":ratio(net,estimated),
        "observed_net_to_planned_stop_loss":ratio(net,risk),
        "observed_fees_to_filled_notional":ratio(fees,notional),
        "observed_net_before_funding":money(net),"observed_fees":money(fees),
        "estimated_target_to_stop":ratio(target,risk),
        "data_notes":[]}
    if not compatible:out["data_notes"].append("unsupported_or_inconsistent_product_or_leverage")
    if len(matches)!=1:out["data_notes"].append("settlement_wallet_unavailable")
    if estimated is None:out["data_notes"].append("fill_margin_estimate_unavailable")
    if risk is None:out["data_notes"].append("stop_exposure_estimate_unavailable")
    if planned is not None and estimated is not None:
        out["filled_margin_estimate_minus_planned_budget"]=money(estimated-planned)
    return out

def cohort(rows):
    """Descriptive per-currency relative exposure groups, not trading thresholds."""
    groups=defaultdict(list)
    for r in rows:
        a=r["allocation"];v=dec(a.get("estimated_stop_loss_to_wallet_balance"))
        net=dec(a.get("observed_net_before_funding"));currency=a.get("currency")
        if v is not None and net is not None and currency:
            groups[currency].append((v,net))
    out=[]
    for currency,values in sorted(groups.items()):
        values.sort()
        # Split at observed median; ties stay together. Never rank by future outcome.
        n=len(values);mid=values[n//2][0] if n%2 else (values[n//2-1][0]+values[n//2][0])/2
        for name,subset in (("at_or_below_sample_median",[x for x in values if x[0]<=mid]),
                            ("above_sample_median",[x for x in values if x[0]>mid])):
            if not subset:continue
            ns=[x[1] for x in subset]
            out.append({"currency":currency,"group":name,"sample_median_stop_to_balance":str(mid),
                "samples":len(ns),"wins":sum(n>0 for n in ns),"net_before_funding":str(sum(ns)),
                "mean_net_before_funding":str(sum(ns)/len(ns))})
    return out

def report(root,symbol):
    if symbol not in SYMBOLS:raise ValueError("unsupported symbol")
    root=Path(root);p=read_performance(root,symbol);rv=read_review(root,symbol,p)
    records=sql(root/"decisions.sqlite","SELECT id,model,status,context,result FROM decisions WHERE symbol=?",(symbol,))
    rows=[]
    for ep in p.get("recent_episodes",[]):
        if ep.get("attribution")!="single_recover_entry_order":continue
        ident=ep.get("decision_id")
        record=unique_match(records or [],lambda x:x[0]==ident and x[2]=="proposed")
        review=unique_match(rv.get("recent",[]),lambda x:x.get("id")==ident and x.get("outcome")=="closed_reconciled"
            and dec(x.get("net_before_funding"))==dec(ep.get("net_before_funding")))
        if not record:continue
        c,r=obj(record[3]),obj(record[4])
        if c.get("symbol")!=symbol or r.get("symbol")!=symbol or r.get("action")!="trade":continue
        rows.append({"decision_id":ident,"model":record[1],"closed":ep.get("closed"),
            "direction":ep.get("direction"),"allocation":allocation(c,r,review or {},ep)})
    expected=mapping(p.get("recover_attributed")).get("closed_episodes")
    return {"version":VERSION,"symbol":symbol,"execution_effect":"none","status":p.get("status"),
        "validation":"descriptive_only","coverage":{"expected_attributed_episodes":expected,"reported":len(rows),
        "complete_window":type(expected) is int and expected==len(rows),"decision_journal_available":records is not None},
        "trades":rows,"cohorts":cohort(rows),
        "limitations":["Estimates use linear same-currency products at recorded 20x leverage; not actual exchange margin or liquidation exposure.",
        "Wallet snapshot is historical balance/available balance, not current equity or total portfolio capital.",
        "Original SL and TP applied to actual fill are planned exposure estimates, not realized loss limits or verified exchange triggers.",
        "Net before funding excludes funding and AI costs; return on estimated initial margin is not an account return.",
        "Cohorts are retrospective descriptive sample splits, not calibrated confidence or causal evidence.",
        "No fixed allocation, size recommendation, trade rejection or live policy change."]}
def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",default="/var/lib/recover-trading/demo")
    p.add_argument("--symbol",required=True,choices=SYMBOLS);a=p.parse_args()
    print(json.dumps(report(Path(a.data_dir)/a.symbol,a.symbol),allow_nan=False,indent=2))
if __name__=="__main__":main()
