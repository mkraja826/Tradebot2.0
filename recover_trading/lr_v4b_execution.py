"""Opt-in LR-V4-B entry adapter for the existing Delta India demo executor.

Not wired to the service cycle. Management integration must precede activation.
Sizing is supplied by the caller's configured AI; prices and direction come
from the strategy and fresh executable demo quotes, not the sizing response.
"""
import time
from decimal import ROUND_FLOOR, ROUND_CEILING
from .broker import DeltaDemo, DEMO_API
from .execution import account_context
from .decision import validate
from .performance import dec
from .lifecycle import pages
from .lr_v4b_attribution import Attribution


def bracket_proposal(signal, sizing, account):
    if signal.get("symbol") != "BTCUSD" or signal.get("version") != "lr-v4b":
        raise ValueError("wrong strategy or market")
    side=signal["side"]
    if side not in ("buy","sell"):
        raise ValueError("invalid side")
    if sizing.get("symbol") != "BTCUSD" or sizing.get("action") != "trade" or sizing.get("side") != side:
        raise ValueError("sizing proposal mismatch")
    if account["product"].get("symbol") != "BTCUSD":
        raise ValueError("product mismatch")
    quote=account.get("decision_quote") or {}
    if quote.get("status") != "fresh_book":
        raise ValueError("fresh executable quote required")
    entry=dec(quote.get("best_ask" if side=="buy" else "best_bid"))
    stop=dec(signal["initial_stop"])
    tick=dec(account["product"].get("tick_size"))
    if any(x is None or x<=0 for x in (entry,stop,tick)):
        raise ValueError("invalid price or tick")
    d=1 if side=="buy" else -1
    stop=(stop/tick).to_integral_value(rounding=ROUND_FLOOR if d==1 else ROUND_CEILING)*tick
    risk=d*(entry-stop)
    target=entry+d*2*risk
    target=(target/tick).to_integral_value(rounding=ROUND_CEILING if d==1 else ROUND_FLOOR)*tick
    if risk<=0 or min(stop,target)<=0:
        raise ValueError("invalid bracket")
    p={"symbol":"BTCUSD","action":"trade","side":side,"size":sizing.get("size"),
       "leverage":sizing.get("leverage"),"capital_allocation":sizing.get("capital_allocation"),
       "entry_reference":float(entry),"stop_loss":float(stop),"take_profit":float(target),
       "reason":"LR-V4-B deterministic bracket; AI sizing"}
    return validate(p,"BTCUSD",require_capital=True)


def submit(signal, sizing, executor, *, enabled=False, clock=time.time):
    """One demo order at most. Never replay an ambiguous submission."""
    if not enabled:
        return {"status":"disabled","execution_effect":"none"}
    if not isinstance(executor.broker,DeltaDemo) or DEMO_API!="https://cdn-ind.testnet.deltaex.org":
        raise ValueError("demo client required")
    if signal.get("symbol")!="BTCUSD" or signal.get("version")!="lr-v4b":
        raise ValueError("BTC LR-V4-B only")
    if sizing.get("action")=="no_trade":
        return {"status":"no_trade","execution_effect":"none"}
    now=int(clock())
    t=signal.get("signal_time")
    if type(t) is not int or not 0<=now-t<60:
        return {"status":"stale_signal","execution_effect":"none"}
    account=account_context(executor.broker,"BTCUSD")
    pid=account["product"]["id"]
    proposal=bracket_proposal(signal,sizing,account)
    # Ownership is position-level on this broker: never merge with another strategy.
    positions=executor.broker.margined_positions(pid)
    if not isinstance(positions,list):
        raise ValueError("position schema")
    for p in positions:
        if str(p.get("product_id"))!=str(pid):
            raise ValueError("position identity mismatch")
        q=dec(p.get("size"))
        if q is None:
            raise ValueError("position size unverified")
        if q!=0:
            return {"status":"existing_position","execution_effect":"none"}
    active,complete=pages(executor.broker.active_orders_page,pid)
    if not complete or active:
        return {"status":"active_orders_or_incomplete","execution_effect":"none"}
    db=executor.journal.db
    if db.execute("SELECT 1 FROM orders WHERE symbol='BTCUSD' AND status IN ('submitting','unknown') LIMIT 1").fetchone():
        return {"status":"unresolved_submission","execution_effect":"none"}
    # Recheck signal lifetime after broker reads.
    now=int(clock())
    if not 0<=now-t<60:
        return {"status":"stale_signal","execution_effect":"none"}
    # Preserve the exchange-rounded structural stop as original risk basis.
    claim=Attribution(db).reserve({**signal,"initial_stop":proposal["stop_loss"]},now)
    if claim is None:
        return {"status":"already_reserved","execution_effect":"none"}
    result=executor.execute({"symbol":"BTCUSD","status":"proposed",
                             "decision_id":claim["decision_id"],"proposal":proposal},account=account)
    with db:
        db.execute("UPDATE lr_v4b_entries SET state=? WHERE signal_id=?",
                   (result["status"],claim["decision_id"]))
    return result
