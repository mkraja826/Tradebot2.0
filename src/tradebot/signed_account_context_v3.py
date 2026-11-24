"""Signed account evidence from caller-supplied authorized read-only clients."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from tradebot.delta import DEMO_API
from tradebot.signed_margin_mode import _parent_signed_subaccount_mode,_user_id
from tradebot.equity_receipt import validate_receipt
from tradebot.isolated_dashboard import _sanitized_positions,_signed_brackets
from tradebot.product_context_v3 import product_spec

LABELS={"BTCUSD":"BTC","XAUTUSD":"GOLD"}

def amount(value,*,zero=False):
    try: d=Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError("invalid_amount") from None
    if not d.is_finite() or d<0 or (not zero and d==0): raise ValueError("invalid_amount")
    return str(d)

def read_signed_context(symbol,child,parent,*,clock=lambda:datetime.now(timezone.utc),stage=lambda _:None):
    label=LABELS[symbol]
    for c in (child,parent):
        if c is None or getattr(c,"base_url",None)!=DEMO_API or getattr(c,"allow_orders",None) is not False:
            raise ValueError("readonly_demo_required")
    started=clock()
    stage("child_preferences")
    prefs=child._request("GET","/v2/users/trading_preferences",auth=True)["result"]
    stage("parent_identity")
    mode=_parent_signed_subaccount_mode(_user_id(prefs["user_id"]),prefs.get("margin_mode"),parent_exchange=parent,expected_label=label)
    if mode!="isolated": raise ValueError("isolated_identity_unverified")
    stage("product")
    raw=child._request("GET","/v2/products/"+symbol)["result"]
    spec=product_spec(raw,symbol,int(clock().timestamp()))
    pid=spec["product_id"]
    stage("leverage")
    setting=child._request("GET",f"/v2/products/{pid}/orders/leverage",auth=True)["result"]
    if str(setting.get("product_id"))!=str(pid): raise ValueError("wrong_leverage_product")
    leverage=amount(setting["leverage"])
    stage("positions")
    inventory=child._request("GET","/v2/positions/margined",auth=True)["result"]
    rows=inventory if isinstance(inventory,list) else [inventory]
    positions=_sanitized_positions(rows,symbol)
    if len(positions)==10: raise ValueError("inventory_may_be_truncated")
    if any(p["symbol"]!=symbol for p in positions): raise ValueError("unexpected_exposure")
    stage("open_orders")
    orders=child.open_orders()
    if not isinstance(orders,list) or len(orders)>200: raise ValueError("order_inventory_unverified")
    for order in orders:
        if not isinstance(order,dict) or order.get("product_symbol")!=symbol or str(order.get("product_id"))!=str(pid):
            raise ValueError("unexpected_or_unverified_order_exposure")
        if order.get("state") not in ("open","pending"):
            raise ValueError("unexpected_order_state")
    _signed_brackets(positions,orders)
    stage("wallet")
    wallet=child.wallet_balances()
    now=clock()
    if not 0<=(now-started).total_seconds()<=60: raise ValueError("account_snapshot_slow")
    equity=amount(wallet["meta"]["net_equity"])
    stage("wallet_receipt")
    observed=validate_receipt(equity,wallet["equity_read_receipt"],now=now)
    stage("usd_balance")
    usd,=(r for r in wallet["balances"] if r.get("asset_symbol")=="USD")
    available=amount(usd["available_balance"],zero=True)
    return {"symbol":symbol,"subaccount":label,"status":"signed_read_only",
            "signed_account_verified":True,"wallet_receipt_verified":True,
            "observed_at":observed.isoformat(),"net_equity_usd":equity,"available_margin_usd":available,
            "configured_leverage":leverage,"leverage_limit":None,"product":spec,
            "available_margin_basis":"usd_wallet_available_balance_not_broker_order_margin_quote",
            "order_inventory_scope":"account_wide_same_product",
            "open_order_states":{k:sum(o["state"]==k for o in orders) for k in ("open","pending")},
            "positions":positions,"open_order_count":len(orders),
            "execution_authorized":False,"paid_dispatch_authorized":False}
