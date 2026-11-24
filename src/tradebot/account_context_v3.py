"""Sanitized account context from the existing read-only dashboard verifier."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from tradebot.product_context_v3 import account_unavailable

LABELS={"BTCUSD":"BTC","XAUTUSD":"GOLD"}
def positive_text(x):
    try: d=Decimal(str(x))
    except (ValueError,InvalidOperation): raise ValueError("invalid_equity") from None
    if not d.is_finite() or d<=0: raise ValueError("invalid_equity")
    return str(d)

def project(report,symbol,*,now):
    label=LABELS[symbol]
    result=account_unavailable(symbol)
    if not isinstance(report,dict) or report.get("environment")!="delta-india-demo" or report.get("mode")!="read_only" or report.get("source")!="isolated_child_accounts":
        return result
    a=report.get("accounts",{}).get(label,{})
    result["halted"]=a.get("halted") if type(a.get("halted")) is bool else None
    result["dashboard_status"]=a.get("status")
    try:
        if a.get("label")!=label or a.get("symbol")!=symbol or a.get("status")!="connected" or a.get("margin_mode")!="isolated_verified":
            raise ValueError("isolated_account_unverified")
        at=datetime.fromisoformat(a["broker_checked_at"])
        if at.tzinfo is None or not 0<=(now-at).total_seconds()<=60: raise ValueError("stale_account")
        equity=positive_text(a["net_equity"])
        positions=a["positions"]; n=a["live_position_count"]; orders=a["open_orders"]
        if not isinstance(positions,list) or type(n) is not int or n!=len(positions) or type(orders) is not int or orders<0:
            raise ValueError("invalid_inventory")
        if any(p.get("symbol")!=symbol for p in positions): raise ValueError("unexpected_exposure")
        view=[]
        for p in positions:
            q={k:p.get(k) for k in ("symbol","size","side","entry","mark","liquidation","unrealized_pnl")}
            pr=p.get("protection") or {}
            q["protection"]={k:pr.get(k) for k in ("status","stop_loss","take_profit","source")}
            view.append(q)
        result.update(status="partial",signed_account_verified=True,broker_checked_at=at.isoformat(),
                      net_equity_usd=equity,positions=view,open_order_count=orders,
                      available_margin_usd=None,leverage_limit=None,
                      reason="signed_wallet_receipt_and_available_margin_not_exposed")
    except (ValueError,TypeError,KeyError,AttributeError):
        pass
    return result

def collect_dashboard(data_dir):
    from tradebot.isolated_dashboard import IsolatedAccountsDashboard
    report=IsolatedAccountsDashboard(data_dir).refresh()
    now=datetime.now(timezone.utc)
    return {s:project(report,s,now=now) for s in LABELS}
