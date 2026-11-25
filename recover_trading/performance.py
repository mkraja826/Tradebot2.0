"""Read-only flat-to-flat fill accounting, with explicit attribution limits."""
import hashlib,json,sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from decimal import Decimal,InvalidOperation
from pathlib import Path

def dec(x):
    try:
        v=Decimal(str(x))
        return v if v.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):return None

def stamp(f):
    try:
        t=datetime.fromisoformat(f["created_at"].replace("Z","+00:00"))
        return t if t.tzinfo is not None else None
    except (KeyError,ValueError,TypeError,AttributeError):return None

def stats(rows):
    n=len(rows); wins=sum(dec(x["net_before_funding"])>0 for x in rows)
    return {"closed_episodes":n,"wins_before_funding":wins,
        "losses_before_funding":sum(dec(x["net_before_funding"])<0 for x in rows),
        "breakeven_before_funding":sum(dec(x["net_before_funding"])==0 for x in rows),
        "win_rate_before_funding":wins/n if n else None,
        "gross_pnl":str(sum((dec(x["gross_pnl"]) for x in rows),Decimal(0))) if n else None,
        "fees":str(sum((dec(x["fees"]) for x in rows),Decimal(0))) if n else None,
        "net_before_funding":str(sum((dec(x["net_before_funding"]) for x in rows),Decimal(0))) if n else None}

def account(fills,spec,order_map,*,complete):
    currency=(spec.get("settling_asset") or {}).get("symbol")
    value=dec(spec.get("contract_value"))
    if spec.get("notional_type")!="vanilla" or currency is None or currency!=(spec.get("quoting_asset") or {}).get("symbol") or value is None or value<=0:
        return {"status":"unsupported_product"}
    rows=[];invalid=0;fees_by_currency=defaultdict(Decimal);missing_fee=0
    for f in fills:
        fee=dec(f.get("commission"));asset=f.get("settling_asset_symbol")
        if fee is not None and isinstance(asset,str) and asset:fees_by_currency[asset]+=fee
        else:missing_fee+=1
        t=stamp(f)
        if t is None:invalid+=1
        else:rows.append((t,f))
    rows.sort(key=lambda x:x[0])
    # Equal timestamps have no proven chronological order. Do not infer.
    ties={t for t in (x[0] for x in rows) if sum(y[0]==t for y in rows)>1} if len(rows)<2000 else set()
    if len(rows)>=2000:
        from collections import Counter
        ties={t for t,n in Counter(t for t,f in rows).items() if n>1}
    episodes=[];issues=defaultdict(int);pos=None;episode=None
    for t,f in rows:
        new=f.get("new_position") or {}; after=dec(new.get("size"));size=dec(f.get("size"));price=dec(f.get("price"));fee=dec(f.get("commission"))
        signed=size*(1 if f.get("side")=="buy" else -1) if size is not None and f.get("side") in ("buy","sell") else None
        valid=(t not in ties and after is not None and signed is not None and size>0 and price is not None and price>0
            and fee is not None and f.get("settling_asset_symbol")==currency and str(f.get("product_id"))==str(spec.get("id")))
        if not valid:
            issues["invalid_or_ambiguous_fill"]+=1;pos=None;episode=None;continue
        before=after-signed
        if pos is None:
            # Require an observed flat anchor before crediting an episode.
            pos=after;episode=None;issues["unanchored_fill"]+=1;continue
        if before!=pos or (before*after<0):
            issues["position_discontinuity_or_reversal"]+=1;pos=after;episode=None;continue
        if before==0 and after!=0:
            episode={"start":f["created_at"],"direction":"LONG" if after>0 else "SHORT","cash":Decimal(0),"fees":Decimal(0),"entry_orders":set(),"fills":0}
        if episode is not None:
            episode["cash"]-=signed*price*value;episode["fees"]+=fee;episode["fills"]+=1
            if abs(after)>abs(before):episode["entry_orders"].add(str(f.get("order_id")))
            if after==0:
                broker_gross=dec(new.get("realized_pnl"));broker_fee=dec(new.get("total_commission_paid"))
                tol=Decimal("0.000001")
                if broker_gross is None or broker_fee is None or abs(episode["cash"]-broker_gross)>tol or abs(episode["fees"]-broker_fee)>tol:
                    issues["broker_reconciliation_mismatch"]+=1
                elif complete and not invalid:
                    linked=[order_map.get(x) for x in episode["entry_orders"]]
                    attributed=len(linked)==1 and linked[0] is not None
                    episodes.append({"opened":episode["start"],"closed":f["created_at"],"direction":episode["direction"],
                        "fills":episode["fills"],"gross_pnl":str(episode["cash"]),"fees":str(episode["fees"]),
                        "net_before_funding":str(episode["cash"]-episode["fees"]),
                        "reported_funding":str(dec(new["realized_funding"])) if dec(new.get("realized_funding")) is not None else None,
                        "decision_id":linked[0]["decision_id"] if attributed else None,
                        "active_rules":linked[0]["active_rules"] if attributed else [],
                        "attribution":"single_recover_entry_order" if attributed else "unattributed"})
                else:issues["incomplete_history"]+=1
                episode=None
        pos=after
    owned=[x for x in episodes if x["decision_id"] is not None]
    rule_stats={}
    for ident in sorted({i for x in owned for i in x["active_rules"]}):
        rule_stats[ident]=stats([x for x in owned if ident in x["active_rules"]])
    return {"status":"reconciled_subset" if complete else "incomplete_fill_history","currency":currency,
        "observed_fills":len(fills),"observed_fees_by_currency":{k:str(v) for k,v in fees_by_currency.items()},
        "missing_fee_fields":missing_fee,"invalid_timestamps":invalid,"excluded":dict(issues),
        "all_reconciled":stats(episodes),"recover_attributed":stats(owned),"unattributed":stats([x for x in episodes if x["decision_id"] is None]),
        "active_rule_cooccurrence":rule_stats,"recent_episodes":episodes[-50:],
        "open_episode_observed":episode is not None,"latest_fill_position":str(pos) if pos is not None else None,
        "limitations":["Only flat-anchored position episodes with matching exchange realized P&L and commission.",
            "Pre-Recover and unmatched account fills are never credited to Recover.",
            "Net and win rate exclude funding; unknown funding is not assumed zero.",
            "Rule co-occurrence is overlapping, not causal strategy attribution."]}

def read_performance(root,symbol):
    root=Path(root)
    try:
        with closing(sqlite3.connect((root/"decisions.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            contexts={i:json.loads(c) for i,c in db.execute("SELECT id,context FROM decisions WHERE symbol=?",(symbol,))}
        by_client={hashlib.sha256(("recover:"+i).encode()).hexdigest()[:32]:{"decision_id":i,"active_rules":sorted({v["id"] for v in c.get("new_signals",[])})} for i,c in contexts.items()}
        specs=[c.get("demo_account",{}).get("product") for c in contexts.values() if c.get("demo_account",{}).get("product")]
        if not specs:return {"status":"product_unavailable"}
        spec=specs[-1]
        def identity(p):return (p.get("id"),p.get("symbol"),p.get("contract_value"),p.get("notional_type"),(p.get("settling_asset") or {}).get("symbol"),(p.get("quoting_asset") or {}).get("symbol"))
        if spec.get("symbol")!=symbol or any(identity(p)!=identity(spec) for p in specs):return {"status":"product_spec_conflict"}
        with closing(sqlite3.connect((root/"orders.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            db.execute("BEGIN")
            fills=[json.loads(x[0]) for x in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))]
            latest=db.execute("SELECT detail FROM lifecycle_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 1",(symbol,)).fetchone()
            order_map={}
            for client,raw in db.execute("SELECT client_id,detail FROM orders WHERE symbol=? AND status='acknowledged'",(symbol,)):
                receipt=json.loads(raw or "{}");oid=receipt.get("id")
                if oid is not None and client in by_client and str(receipt.get("product_id"))==str(spec["id"]) and receipt.get("client_order_id")==client:
                    order_map[str(oid)]=by_client[client]
            complete=bool(latest and json.loads(latest[0]).get("fill_window_complete") is True)
        return account(fills,spec,order_map,complete=complete)
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError):
        return {"status":"unavailable_or_invalid_journal"}
