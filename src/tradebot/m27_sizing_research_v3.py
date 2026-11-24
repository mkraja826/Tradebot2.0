"""Offline minimum-contract feasibility and cost stress. Not an admission gate."""
from decimal import Decimal,localcontext,ROUND_CEILING
from tradebot.fire_risk import FireRiskLimits,assess_fire_plan,RiskRejected
from tradebot.m20_subaccount_equity_v3 import number

def review(f,*,now):
    if f.get("mode")!="synthetic_sizing_fixture" or f.get("execution_authorized") is not False:
        raise ValueError("fixture_only")
    s=f["symbol"];p=f["product"];q=f["quote"]
    if s not in ("BTCUSD","XAUTUSD") or p["symbol"]!=s or q["symbol"]!=s:
        raise ValueError("market_mismatch")
    if p["source"]!="delta_demo_public_product" or not 0<=now-p["observed_at"]<=300 or not 0<=now-q["observed_at"]<=60:
        raise ValueError("stale_fixture_context")
    if p["quote_currency"]!="USD" or p["settlement_currency"]!="USD" or p["contract_type"]!="perpetual_futures":
        raise ValueError("product_scope")
    side=f["direction"]
    if side not in ("LONG","SHORT"):raise ValueError("direction")
    tick,unit,bid,ask,stop,target,equity,margin,fee=(number(x) for x in
        (p["tick_size"],p["contract_value"],q["best_bid"],q["best_ask"],f["stop_loss"],f["take_profit"],f["fixture_equity"],f["fixture_available_margin"],f["fixture_taker_rate"]))
    if min(tick,unit,bid,ask,stop,target,equity)<=0 or margin<0 or margin>equity or not 0<=fee<=Decimal("0.05") or bid>ask:
        raise ValueError("numeric_domain")
    if any(x%tick for x in (bid,ask,stop,target)):raise ValueError("off_tick")
    entry=ask if side=="LONG" else bid
    if not (stop<entry<target if side=="LONG" else target<entry<stop):
        raise ValueError("invalid_bracket")
    # Explicit synthetic leverage; retain the existing effective exposure ceiling.
    leverage=f.get("fixture_leverage",5)
    if type(leverage) is not int or not 1<=leverage<=20:raise ValueError("fixture_leverage")
    limits=FireRiskLimits(max_effective_leverage=Decimal(5))
    with localcontext() as ctx:
        ctx.prec=40;ctx.rounding=ROUND_CEILING
        notional=entry*unit
        cost=unit*(entry+stop)*fee+2*notional*limits.slippage_reserve_each_side
        loss=unit*abs(entry-stop)+cost
        margin_estimate=notional/leverage+cost
    out=dict(mode="synthetic_minimum_contract_review",symbol=s,
        execution_authorized=False,orders_submitted=0,broker_margin_verified=False,
        fixture_leverage=leverage,fixture_contracts=1,
        estimated_margin_with_costs=str(margin_estimate),estimated_stop_loss=str(loss),
        stop_execution_guaranteed=False,existing_policy_changed=False)
    if margin_estimate>margin:return dict(out,status="fixture_margin_shortfall")
    plan=dict(direction=side,contracts=1,leverage=leverage,stop_loss=str(stop),take_profit=str(target))
    budget=dict(max_contracts_per_entry=1,leverage=str(leverage),equity_usd=str(equity),contract_value=str(unit),taker_commission_rate=str(fee))
    try:assess_fire_plan(plan,budget,q,limits=limits)
    except RiskRejected:return dict(out,status="existing_risk_validator_rejected_fixture")
    return dict(out,status="minimum_contract_fixture_validated")


def quantity_bound_fixture(f,*,now,contract_ceiling):
    """Offline affordability upper bound; never an executable quantity or approval."""
    from fractions import Fraction
    if type(contract_ceiling) is not int or not 1<=contract_ceiling<=1200:raise ValueError('fixture_ceiling')
    result=review(f,now=now)
    out=dict(result,mode='synthetic_quantity_bound_only',estimated_quantity_upper_bound=0)
    if result['status']!='minimum_contract_fixture_validated':return out
    equity=Fraction(number(f['fixture_equity']));margin=Fraction(number(f['fixture_available_margin']))
    unit=Fraction(number(f['product']['contract_value']))
    entry=Fraction(number(f['quote']['best_ask' if f['direction']=='LONG' else 'best_bid']))
    loss=Fraction(Decimal(result['estimated_stop_loss']));cost=Fraction(Decimal(result['estimated_margin_with_costs']))
    # Retain the existing research risk reference, not a new approved policy.
    loss_cap=(equity*Fraction(1,400))//loss
    margin_cap=margin//cost
    leverage_cap=(equity*5)//(unit*entry)
    return dict(out,estimated_quantity_upper_bound=min(contract_ceiling,loss_cap,margin_cap,leverage_cap),fixture_risk_fraction='0.0025',broker_pretrade_quote_verified=False,production_quantity_verified=False)
