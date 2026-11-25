"""Commission-only break-even and hypothetical exit prices; no order changes."""
from decimal import Decimal
from .performance import dec
VERSION="exit-cost-preview-v1"
BPS=Decimal(10000)

def evaluate(entry,exit_price,sign,rate):
    gross=sign*(exit_price-entry)/entry*BPS
    fee=rate*(entry+exit_price)/entry*BPS
    return {"assumed_exit_fill_price":str(exit_price),"gross_return_bps":float(gross),
        "estimated_commission_bps":float(fee),"net_before_funding_bps":float(gross-fee)}

def build(position,cost):
    out={"version":VERSION,"status":"unavailable","execution_effect":"none",
        "basis":"remaining_position_slice_equal_observed_entry_and_exit_fee_rate",
        "limitations":["Break-even is a hypothetical exit fill price, not an order trigger or price recommendation.",
        "Historical turnover-weighted commission is assumed on both legs of the remaining slice; actual entry fee allocation is not reconstructed.",
        "Prior partial reductions, funding, liquidation, additional charges and realized cashflows are excluded. No leverage multiplier.",
        "A mark or bracket trigger is not an executable exit fill. Half-spread scenario is illustrative, not a slippage prediction."] }
    f=cost.get("fill_commission") or {}
    entry,mark,q=(dec(position.get(k)) for k in ("entry_price","mark_price","size"))
    fee,turnover=(dec(f.get(k)) for k in ("observed_commission","observed_turnover"))
    if cost.get("status")!="observed" or f.get("status")!="observed_subset" or not f.get("samples") or fee is None or turnover is None or turnover<=0 or fee<0:return out
    rate=fee/turnover
    if rate>=1 or any(v is None for v in (entry,mark,q)) or min(entry,mark)<=0 or not q:return out
    sign=1 if q>0 else -1
    # sign*(x-e)-r*(e+x)=0, valid for vanilla linear contracts.
    be=entry*(1+sign*rate)/(1-sign*rate)
    out.update(status="commission_only_estimate",direction="LONG" if sign>0 else "SHORT",remaining_contracts=str(abs(q)),
        entry_price=str(entry),one_way_assumed_fee_bps=float(rate*BPS),fee_fill_samples=f["samples"],
        break_even_exit_fill_price=str(be),break_even_favorable_move_bps=float(sign*(be-entry)/entry*BPS),
        mark_scenario=evaluate(entry,mark,sign,rate))
    if position.get("bracket_state")!="matching_legs_observed":return out
    legs={l.get("type"):dec(l.get("trigger")) for l in position.get("legs",[])}
    for name,kind in (("target","take_profit_order"),("stop","stop_loss_order")):
        p=legs.get(kind)
        if p is None or p<=0:continue
        r=evaluate(entry,p,sign,rate)
        r["trigger_price"]=str(p)
        spread=dec((cost.get("spread") or {}).get("median_full_spread_bps"))
        if spread is not None and 0<=spread<2*BPS:
            adverse=p*(1-sign*spread/(2*BPS))
            if adverse>0:r["illustrative_adverse_half_spread"]=evaluate(entry,adverse,sign,rate)
        out[name+"_scenario"]=r
    return out
