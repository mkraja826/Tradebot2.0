"""Gold-only candidate to existing demo bracket-executor contract.

Preparation is read-only. The submission bridge is intentionally not wired
into a service or CLI until position ownership and management are verified.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from hashlib import sha256
from math import isfinite
from .broker import DeltaDemo
from .entry_quotes import quote_evidence
from .execution import DemoExecutor

VERSION="gold-v2-entry-adapter.1"
SYMBOL="XAUTUSD"
LEVERAGE=20

def dec(x):
    if isinstance(x,bool):raise ValueError("invalid_number")
    y=Decimal(str(x))
    if not y.is_finite():raise ValueError("invalid_number")
    return y

def positive(x):
    y=dec(x)
    if y<=0:raise ValueError("invalid_positive_number")
    return y

def select(report):
    if report.get("symbol")!=SYMBOL:raise ValueError("wrong_symbol")
    if report.get("status")!="observed":return None,"data_unavailable"
    rows=report.get("candidates",[])
    if not rows:return None,"no_candidate"
    directions={c.get("direction") for c in rows}
    if not directions<= {"LONG","SHORT"}:raise ValueError("invalid_direction")
    if len(directions)!=1 or report.get("conflicting_directions"):
        return None,"conflicting_candidates"
    # Alphabetical family is an attribution tie-break only, never a learned rank.
    first=sorted(rows,key=lambda c:c["family"])[0]
    keys=("atr","stop_distance_atr_hypothesis","target_distance_atr_hypothesis")
    if any(tuple(c.get(k) for k in keys)!=tuple(first.get(k) for k in keys) for c in rows):
        return None,"conflicting_bracket_parameters"
    return first,"candidate"

def plan(report,product,wallet,quote,*,allocation_fraction,now):
    candidate,status=select(report)
    if candidate is None:return {"status":status,"execution_effect":"none"}
    fraction=positive(allocation_fraction)
    if fraction>1:raise ValueError("invalid_allocation")
    stamp=report.get("decision_as_of",report.get("as_of"))
    candle=report.get("as_of")
    if (type(stamp) not in (int,float) or type(candle) not in (int,float)
        or not isfinite(stamp) or not isfinite(candle) or not 0<=now-stamp<=120
        or not 0<=stamp-candle<300 or int(now)//300!=int(candle)//300):
        return {"status":"stale_candidate","execution_effect":"none"}
    if (product.get("symbol")!=SYMBOL or type(product.get("id")) is not int
        or product["id"]<=0 or product.get("contract_unit_currency")!="XAUT"
        or product.get("settling_asset",{}).get("symbol")!="USD"
        or product.get("quoting_asset",{}).get("symbol")!="USD"
        or product.get("notional_type")!="vanilla"):
        raise ValueError("unsupported_gold_contract")
    if wallet.get("asset_symbol")!="USD":raise ValueError("wrong_wallet_currency")
    if quote.get("status")!="fresh_book":return {"status":"quote_unavailable","execution_effect":"none"}
    bid,ask,mark=(positive(quote[k]) for k in ("best_bid","best_ask","mark_price"))
    if bid>ask:raise ValueError("crossed_quote")
    entry=ask if candidate["direction"]=="LONG" else bid
    sign=1 if candidate["direction"]=="LONG" else -1
    tick=positive(product["tick_size"]);cv=positive(product["contract_value"])
    a=positive(candidate["atr"])
    balance=positive(wallet["balance"])
    available=dec(wallet["available_balance"])
    if available<=0:return {"status":"no_available_balance","execution_effect":"none"}
    budget=min(balance*fraction,available)
    size=int(budget*LEVERAGE/(entry*cv))
    if size<1:return {"status":"below_one_contract","execution_effect":"none"}
    # Round stop away from entry and target toward entry. Never widen after submit.
    sl_raw=entry-sign*a*positive(candidate["stop_distance_atr_hypothesis"])
    tp_raw=entry+sign*a*positive(candidate["target_distance_atr_hypothesis"])
    rounding=ROUND_FLOOR if sign==1 else ROUND_CEILING
    sl=(sl_raw/tick).to_integral_value(rounding=rounding)*tick
    tp=(tp_raw/tick).to_integral_value(rounding=rounding)*tick
    if min(sl,tp)<=0 or not (sl<min(mark,entry)<=max(mark,entry)<tp if sign==1 else tp<min(mark,entry)<=max(mark,entry)<sl):
        return {"status":"incompatible_bracket","execution_effect":"none"}
    # Same bar gets same id regardless of changing score, side or quote.
    boundary=int(candle)//300*300
    ident=sha256(f"gold-v2:{boundary}".encode()).hexdigest()
    margin=entry*cv*size/LEVERAGE
    return {"status":"proposed","symbol":SYMBOL,"decision_id":ident,
            "execution_effect":"none","version":VERSION,
            "proposal":{"symbol":SYMBOL,"action":"trade","reason":"Gold V2 research candidates: "+",".join(sorted({c["family"] for c in report["candidates"]})),
                        "side":"buy" if sign==1 else "sell","size":size,"leverage":LEVERAGE,
                        "capital_allocation":float(margin),"entry_reference":float(entry),
                        "stop_loss":float(sl),"take_profit":float(tp)},
            "allocation_fraction_requested":float(fraction),
            "margin_estimate_usd":float(margin),"account_margin_verified":False}

def prepare(broker,report,*,expected_gold_account,allocation_fraction,now):
    """Read-only broker checks. Expected account must be operator-verified Gold demo ID."""
    expected=str(expected_gold_account)
    if not expected.isdigit() or int(expected)<=0 or int(expected)==26679287:
        raise ValueError("invalid_gold_account")
    if report.get("symbol")!=SYMBOL:raise ValueError("wrong_symbol")
    wallet,=[w for w in broker.wallet()["result"] if w.get("asset_symbol")=="USD"]
    if str(wallet.get("user_id"))!=expected:raise ValueError("gold_wallet_mismatch")
    product=broker.product(SYMBOL)
    if product.get("symbol")!=SYMBOL or type(product.get("id")) is not int:
        raise ValueError("wrong_product")
    pid=product["id"]
    positions=broker.positions(pid)
    if isinstance(positions,dict):positions=[positions]
    if not isinstance(positions,list) or any(p.get("product_id")!=pid for p in positions):
        raise ValueError("unverified_positions")
    page=broker.active_orders_page(pid)
    if (not isinstance(page.get("result"),list) or not isinstance(page.get("meta"),dict)
        or page["meta"].get("after")):
        return {"status":"incomplete_orders","execution_effect":"none"},None
    if any(dec(p["size"])!=0 for p in positions) or page["result"]:
        return {"status":"existing_exposure","execution_effect":"none"},None
    quote=quote_evidence(broker.ticker(SYMBOL),SYMBOL,pid,int(now*1000000))
    result=plan(report,product,wallet,quote,allocation_fraction=allocation_fraction,now=now)
    return result,{"product":{"id":pid,"symbol":SYMBOL},"decision_quote":quote}

def submit_prepared(executor,report,*,expected_gold_account,allocation_fraction,now,enabled=False):
    """Integration bridge only. Not called by any runtime in this increment."""
    if enabled is not True:return {"status":"disabled","execution_effect":"none"}
    if type(executor) is not DemoExecutor or type(executor.broker) is not DeltaDemo:
        raise ValueError("existing_demo_executor_required")
    if executor.journal.unresolved():
        return {"status":"unresolved_order","execution_effect":"none"}
    # Recheck immediately before dispatch; caller must ensure single Gold owner.
    result,account=prepare(executor.broker,report,expected_gold_account=expected_gold_account,
                           allocation_fraction=allocation_fraction,now=now)
    if result["status"]!="proposed":return result
    return {"decision":result,"execution":executor.execute(result,account=account)}
