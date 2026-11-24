"""Offline comparison of documented standalone isolated-margin price bases."""
from decimal import Decimal,localcontext,ROUND_CEILING
def compare(*,side,kind,mark,bid,ask,limit,unit,contracts,initial_margin_fraction):
    if side not in ('LONG','SHORT') or kind not in ('MARKET','LIMIT'):
        raise ValueError('order_scope')
    if type(contracts) is not int or not 1<=contracts<=1200:raise ValueError('fixture_contracts')
    def number(v):
        if not isinstance(v,str) or len(v)>40:raise ValueError('decimal')
        x=Decimal(v)
        if not x.is_finite() or x<=0 or x.adjusted() not in range(-18,19):raise ValueError('decimal')
        return x
    mark,bid,ask,unit,rate=map(number,(mark,bid,ask,unit,initial_margin_fraction))
    if bid>ask or rate>1:raise ValueError('domain')
    if kind=='MARKET':
        if limit is not None:raise ValueError('market_limit')
        base=mark if side=='LONG' else max(mark,bid)
        entry=ask if side=='LONG' else bid
    else:
        entry=number(limit);base=entry if side=='LONG' else max(entry,bid)
    with localcontext() as c:
        c.prec=160;c.rounding=ROUND_CEILING
        documented=contracts*unit*rate*base
        entry_estimate=contracts*unit*rate*entry
        return dict(mode='synthetic_standalone_margin_comparison',documented_price_basis=str(base),
            documented_initial_margin=str(documented),entry_price_initial_margin=str(entry_estimate),
            difference=str(documented-entry_estimate),fees_included=False,
            account_margin_tier_verified=False,existing_exposure_accounted_for=False,
            broker_quote_verified=False,execution_authorized=False)


def tier_fee_fixture(*,side,kind,mark,bid,ask,limit,unit,contracts,
                     minimum_margin_pct,threshold_usd,slope_pct_per_usd,
                     selected_leverage,entry_fee_fraction,exit_fee_fraction,
                     estimated_exit_price):
    """Synthetic standalone estimate; assumes flat inventory and explicit tier units."""
    from fractions import Fraction
    def number(v,zero=False):
        if not isinstance(v,str) or len(v)>40:raise ValueError('decimal')
        try:d=Decimal(v)
        except ArithmeticError:raise ValueError('decimal') from None
        if not d.is_finite() or d<0 or (not zero and d==0) or (d and d.adjusted() not in range(-18,19)):
            raise ValueError('decimal')
        return Fraction(d)
    if type(selected_leverage) is not int or not 1<=selected_leverage<=20:
        raise ValueError('fixture_leverage')
    raw=compare(side=side,kind=kind,mark=mark,bid=bid,ask=ask,limit=limit,
                unit=unit,contracts=contracts,initial_margin_fraction='0.05')
    qty=number(unit)*contracts
    notional=qty*number(raw['documented_price_basis'])
    tier=number(minimum_margin_pct)/100+number(slope_pct_per_usd,True)/100*max(Fraction(0),notional-number(threshold_usd))
    fees=[number(x,True) for x in (entry_fee_fraction,exit_fee_fraction)]
    if tier>1 or max(fees)>Fraction(1,20):raise ValueError('rate_domain')
    rate=max(tier,Fraction(1,selected_leverage))
    entry=number(limit if kind=='LIMIT' else ask if side=='LONG' else bid)
    fee_reserve=qty*(entry*fees[0]+number(estimated_exit_price)*fees[1])
    margin=notional*rate
    def out(x):
        with localcontext() as c:
            c.prec=40;c.rounding=ROUND_CEILING
            return str(Decimal(x.numerator)/Decimal(x.denominator))
    return dict(mode='synthetic_flat_inventory_tier_fee_reference',
        notional=out(notional),tier_margin_fraction=out(tier),
        estimated_margin_fraction=out(rate),estimated_initial_margin=out(margin),
        estimated_fee_reserve=out(fee_reserve),estimated_total_reserve=out(margin+fee_reserve),
        broker_quote_verified=False,account_tier_verified=False,fee_schedule_verified=False,
        execution_authorized=False)
