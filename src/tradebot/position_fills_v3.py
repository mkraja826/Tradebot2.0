"""Read-only fill lifecycle projection. Never submits orders or declares settlement."""
from decimal import Decimal,localcontext
from tradebot.fire_reconciliation import normalize_fill,unique,analyse,ReconciliationError
from tradebot.position_observer_v3 import number

def fill_progress(symbol,product_id,direction,entry_order,exit_orders,raw_fills):
    if symbol not in ("BTCUSD","XAUTUSD") or direction not in ("LONG","SHORT"):
        raise ValueError("invalid_trade_scope")
    entry_order=str(entry_order); exit_orders={str(x) for x in exit_orders}
    if not entry_order or entry_order in exit_orders or not exit_orders: raise ValueError("invalid_order_scope")
    fills=unique([normalize_fill(x) for x in raw_fills])
    selected=[f for f in fills if f["order_id"]==entry_order or f["order_id"] in exit_orders]
    if any(f["symbol"]!=symbol or f["product_id"]!=str(product_id) or f["asset"]!="USD" for f in selected):
        raise ValueError("wrong_fill_scope")
    entry_side="buy" if direction=="LONG" else "sell"
    q=Decimal(0); entered=Decimal(0); exited=Decimal(0)
    # Equal-time entry/exit sequencing is ambiguous unless signed position evidence establishes order.
    if len({f["at_us"] for f in selected})!=len(selected): raise ValueError("ambiguous_fill_order")
    for f in selected:
        n=number(f["size"],True)
        if f["order_id"]==entry_order:
            if f["side"]!=entry_side or exited: raise ValueError("unexpected_entry")
            entered+=n; q+=n
        else:
            if f["side"]==entry_side or n>q: raise ValueError("unexpected_exit")
            exited+=n; q-=n
    status="no_entry_fill" if not entered else "exit_fills_observed" if q==0 else "partial_exit_observed" if exited else "entry_fills_observed"
    return {"symbol":symbol,"direction":direction,"status":status,"entered_contracts":str(entered),
            "exited_contracts":str(exited),"remaining_contracts":str(q),"matched_fill_ids":[f["id"] for f in selected],
            "settlement_verified":False,"net_realized_pnl_usd":None,"execution_authorized":False}

def completed_trade(symbol,trade,product,orders,fills,postings,start_us,end_us):
    """Accept normalized evidence only from the caller's existing signed read-only path.
    Reuse strict broker reconciliation; this does not authenticate transport itself.
    """
    if trade.get("status") not in ("flat_verified","aborted_flat","cancelled_flat_verified"): raise ValueError("terminal_receipt_required")
    with localcontext() as context:
        context.prec=128
        result=analyse(symbol,trade,product,orders,unique(fills),unique(postings),start_us,end_us)
    if result.get("is_net_realized_pnl") is not True or result.get("funding_reconciled") is not True:
        raise ValueError("unverified_settlement")
    return {"symbol":symbol,"trade_id":trade["id"],"source":"existing_reconciliation_algorithm",
            "evidence":result,"execution_authorized":False}
