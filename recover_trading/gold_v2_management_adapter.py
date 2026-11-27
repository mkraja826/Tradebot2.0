"""Gold V2 position-management proposal adapter; no network or order writes.

This adapter accepts an externally verified entry receipt and position snapshot.
It intentionally does not adopt legacy or resized positions.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from hashlib import sha256
from math import isfinite
from .position_preview import observe
from .management_executor import identity
from .management_shadow import VERSION as SHADOW_VERSION
from .management_lifecycle import plan as lifecycle_plan
from .gold_v2_entry_adapter import SYMBOL

VERSION="gold-v2-management-adapter.2"

def dec(x):
    if isinstance(x,bool):raise ValueError("invalid_number")
    y=Decimal(str(x))
    if not y.is_finite():raise ValueError("invalid_number")
    return y

def positive(x):
    y=dec(x)
    if y<=0:raise ValueError("invalid_positive")
    return y

def ownership(snapshot,entry,product,now):
    """Check original, fully filled V2 entry against current position.
    entry contains signal_boundary, journal_client_id, intent and exchange receipt.
    Caller must retrieve those from trusted journal and exchange reads.
    """
    if product.get("symbol")!=SYMBOL or type(product.get("id")) is not int:
        return None
    v=observe(snapshot,SYMBOL,now)
    if v["position_state"] not in ("long","short") or v["bracket_state"]!="matching_legs_observed":
        return None
    if len(snapshot["active_orders"])!=2 or any(o.get("stop_trigger_method")!="mark_price" for o in snapshot["active_orders"]):
        return None
    ident=identity(snapshot)
    if ident is None:return None
    try:
        boundary=entry["signal_boundary"]
        if type(boundary) is not int or boundary<=0 or boundary%300 or boundary>now:return None
        decision=sha256(f"gold-v2:{boundary}".encode()).hexdigest()
        cid=sha256(("recover:"+decision).encode()).hexdigest()[:32]
        if entry["journal_client_id"]!=cid:return None
        intent=entry["intent"];r=entry["receipt"];p=snapshot["positions"][0]
        q=dec(v["size"]);signed=int(q)
        if q!=signed or not signed:return None
        side="buy" if signed>0 else "sell"
        pid=product["id"]
        if (r.get("id") is None or r.get("client_order_id")!=cid
            or r.get("state")!="closed" or r.get("reduce_only") is not False
            or r.get("side")!=side or intent.get("side")!=side
            or any(str(x)!=str(pid) for x in (p.get("product_id"),r.get("product_id"),intent.get("product_id")))
            or dec(r["unfilled_size"])!=0 or dec(r["size"])!=abs(q)
            or dec(intent["size"])!=abs(q)
            or positive(r["average_fill_price"])!=positive(v["entry_price"])
            or p.get("created_at")!=entry.get("verified_position_created_at")):
            return None
        sl,tp=positive(intent["stop_loss"]),positive(intent["take_profit"])
        if positive(r["bracket_stop_loss_price"])!=sl or positive(r["bracket_take_profit_price"])!=tp:
            return None
        return {"identity":ident,"size":signed,"entry_price":positive(v["entry_price"]),
                "initial_stop":sl,"initial_target":tp,"view":v,"client_id":cid}
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return None

def evaluate(report,snapshot,product,entry,*,now,history):
    return _evaluate(report,snapshot,product,entry,now=now,history=history)

def evaluate_episode(report,snapshot,product,seed,receipt,fills,reductions,*,now,history,complete):
    """Reconcile exact fill chain anew before producing a management proposal."""
    from .gold_v2_episode import reconcile
    state=reconcile(seed,receipt,fills,reductions,snapshot,now=now,complete=complete)
    if state["status"]!="owned_open":
        return {"version":VERSION,"symbol":SYMBOL,"status":state["status"],"execution_effect":"none"}
    if product.get("symbol")!=SYMBOL or product.get("id")!=seed["product_id"]:
        raise ValueError("wrong_product")
    owned=dict(state,entry_price=positive(state["entry_price"]),initial_stop=positive(state["initial_stop"]),initial_target=positive(state["initial_target"]))
    entry={"signal_boundary":seed["signal_boundary"],"signal_atr":seed["signal_atr"],"first_full_bar_close":state["first_full_bar_close"]}
    return _evaluate(report,snapshot,product,entry,now=now,history=history,reconciled=owned)

def _evaluate(report,snapshot,product,entry,*,now,history,reconciled=None):
    """Return at most one compatible proposal, with no execution authority.

    history is trusted completed 5m bars from the owned episode, oldest first.
    No resizing upward: existing executor has no verified add-and-rebracket API.
    """
    def out(status,**kwargs):return {"version":VERSION,"symbol":SYMBOL,"status":status,"execution_effect":"none",**kwargs}
    if report.get("symbol")!=SYMBOL or snapshot.get("symbol")!=SYMBOL:
        raise ValueError("wrong_symbol")
    if type(now) is not int:raise ValueError("invalid_now")
    owned=reconciled if reconciled is not None else ownership(snapshot,entry,product,now)
    if owned is None:return out("ownership_or_protection_unverified")
    if report.get("status")!="observed":return out("market_data_unavailable")
    at=report.get("as_of");decision=report.get("decision_as_of",at)
    if (type(at) not in (int,float) or type(decision) not in (int,float)
        or not isfinite(at) or not isfinite(decision) or not 0<=now-decision<=120
        or not 0<=decision-at<300 or int(now)//300!=int(at)//300):
        return out("market_data_stale")
    boundary=int(at)//300*300
    # The caller must establish the episode's first complete post-fill bar.
    first=entry.get("first_full_bar_close")
    if (type(first) is not int or first%300 or first<=entry["signal_boundary"]
        or not history or history[0].ts!=first or history[-1].ts!=boundary
        or any(b.ts!=first+300*i or not all(isfinite(x) for x in (b.o,b.h,b.l,b.c))
               or not 0<b.l<=min(b.o,b.c)<=max(b.o,b.c)<=b.h for i,b in enumerate(history))):
        return out("episode_history_unverified")
    frame=report.get("features",{});f=frame.get(300,frame.get("300",{}))
    try:
        a=positive(f["atr"]);ema=positive(f["ema"][0]);a0=positive(entry["signal_atr"])
        tick=positive(product["tick_size"]);mark=positive(owned["view"]["mark_price"])
        legs={l["type"]:positive(l["trigger"]) for l in owned["view"]["legs"]}
        sl,tp=legs["stop_loss_order"],legs["take_profit_order"]
        fill=owned["entry_price"];q=owned["size"];side=1 if q>0 else -1
        if not (sl<mark<tp if side==1 else tp<mark<sl):return out("crossed_existing_bracket")
        if side*(sl-owned["initial_stop"])<0:return out("existing_stop_loosened")
        close=positive(history[-1].c)
        best=max([fill]+[positive(b.c) for b in history]) if side==1 else min([fill]+[positive(b.c) for b in history])
        best_move=side*(best-fill)/a0;move=side*(close-fill)/a0
        action={"symbol":SYMBOL,"action":"maintain","reason":"No completed-bar management change"}
        # Full exit precedes bracket edits and reductions.
        if best_move>=1 and best_move-move>=Decimal(".75"):
            action.update(action="close",reason="Gold V2 close-based profit giveback")
        elif move<=Decimal("-.5") and abs(q)>=2 and not owned.get("reduced",False):
            action.update(action="reduce",contracts=abs(q)//2,reason="Gold V2 adverse close reduction")
        else:
            levels=[]
            if best_move>=Decimal(".75"):
                levels.extend([best-side*Decimal("1.5")*a,ema-side*Decimal(".25")*a])
                if len(history)>=3:
                    level=min(b.l for b in history[-3:]) if side==1 else max(b.h for b in history[-3:])
                    levels.append(dec(level)-side*Decimal(".1")*a)
                if best_move>=1 and not owned.get("reduced",False):
                    # Entry-only estimate, not actual episode net breakeven.
                    levels.append(fill*(1+side*Decimal(".0015")))
            rounding=ROUND_FLOOR if side==1 else ROUND_CEILING
            rounded=[(p/tick).to_integral_value(rounding=rounding)*tick for p in levels]
            eligible=[p for p in rounded if p>0 and side*(p-sl)>0 and side*(mark-p)>0 and side*(close-p)>0 and side*(tp-p)>0]
            if eligible:
                new=max(eligible,key=lambda p:side*p)
                action.update(action="update_bracket",stop_loss=float(new),take_profit=float(tp),reason="Gold V2 tighten stop")
            elif len(history)>=2 and tp==owned["initial_target"]:
                prev=history[-2];last=history[-1]
                if (side*(tp-fill)>0 and side*(close-fill)>=Decimal(".6")*side*(tp-fill)
                    and side*(close-dec(prev.c))>0 and side*(dec(prev.c)-dec(prev.o))>0
                    and side*(close-dec(last.o))>=Decimal(".25")*a0):
                    new=((tp+side*a0)/tick).to_integral_value(rounding=rounding)*tick
                    if new>0 and side*(new-tp)>0 and side*(new-mark)>0:
                        action.update(action="update_bracket",stop_loss=float(sl),take_profit=float(new),reason="Gold V2 momentum target extension")
        context={"version":SHADOW_VERSION,"symbol":SYMBOL,"as_of":int(decision),
                 "position_observed":owned["view"]["observed"],"execution_identity":owned["identity"],
                 "product":{"id":product["id"],"tick_size":str(tick)},
                 "position":{"direction":owned["view"]["position_state"],"size":q,
                     "entry_price":str(fill),"mark_price":str(mark),"bracket_state":"matching_legs_observed",
                     "legs":owned["view"]["legs"]}}
        validated=lifecycle_plan(context,action)
        return out("proposal_prepared",proposal=action,context=context,lifecycle_preview=validated,
                   entry_client_id=owned["client_id"],bar_boundary=boundary,
                   unsupported=["position_addition","partial_limit_booking"] + ([] if reconciled is not None else ["post_reduction_ownership"]))
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return out("invalid_management_evidence")
