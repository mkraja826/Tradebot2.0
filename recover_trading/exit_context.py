"""Descriptive exit geometry, not an execution policy or profit forecast."""
from .performance import dec
VERSION="exit-context-v1"

def geometry(position,excursion=None,raw_position=None,direction=None):
    out={"version":VERSION,"status":"unavailable","execution_effect":"none",
        "capabilities":{"update_bracket":"stop_loss_only_keep_existing_take_profit","reduce":"positive_integer_less_than_position","close":"full_reduce_only","repair_bracket":"no_active_orders_only"}}
    e,m,q=(dec(position.get(k)) for k in ("entry_price","mark_price","size"))
    if any(v is None for v in (e,m,q)) or min(e,m)<=0 or not q:return out
    sign=1 if q>0 else -1
    def bps(price):return float(sign*(price-e)/e*10000)
    out.update(status="observed_mark_geometry",current_gross_mark_return_bps=bps(m),
        direction_consensus_relation="aligned" if direction==("LONG" if q>0 else "SHORT") else "opposed" if direction==("SHORT" if q>0 else "LONG") else "neutral_or_unknown")
    if position.get("bracket_state")=="matching_legs_observed":
        legs={r.get("type"):dec(r.get("trigger")) for r in position.get("legs",[])}
        sl,tp=legs.get("stop_loss_order"),legs.get("take_profit_order")
        if sl is not None and tp is not None and min(sl,tp)>0:
            downside=sign*(m-sl);upside=sign*(tp-m)
            out.update(stop_trigger_gross_entry_return_bps=bps(sl),target_trigger_gross_entry_return_bps=bps(tp),
                mark_to_stop_bps=float(downside/m*10000),mark_to_target_bps=float(upside/m*10000),
                remaining_target_to_stop_distance_ratio=float(upside/downside) if downside>0 and upside>0 else None,
                trigger_geometry="straddles_mark" if downside>0 and upside>0 else "crossed_or_at_mark")
    if isinstance(excursion,dict):
        mfe=dec(excursion.get("mfe_bps"));mae=dec(excursion.get("mae_bps"))
        if mfe is not None and mae is not None and min(mfe,mae)>=0:
            mark_return=dec(out["current_gross_mark_return_bps"])
            out["observed_excursion"]={"mfe_trade_price_lower_bound_bps":float(mfe),"mae_trade_price_lower_bound_bps":float(mae),
                "observed_trade_peak_minus_current_mark_bps":float(max(0,mfe-mark_return)),
                "coverage":excursion.get("coverage"),"status":excursion.get("status"),"holding_seconds":excursion.get("holding_seconds"),
                "partial_reduction_fills":excursion.get("partial_reduction_fills"),
                "basis":"mixed_trade_extrema_and_mark_not_executable_giveback"}
    if isinstance(raw_position,dict):
        out["exchange_reported_position_amounts"]={k:str(v) for k in ("unrealized_pnl","realized_pnl","realized_funding","commission","realized_cashflow") if (v:=dec(raw_position.get(k))) is not None}
    out["limitations"]="Gross price distances, not net P&L or expected value. Stop trigger is not guaranteed fill; fees, funding, slippage and liquidation may affect outcome. Excursion compares trade extrema to mark, not verified giveback."
    return out
