"""Synthetic transfer-neutral equity index for independent policy review.

No broker transport, risk admission, deployment or release integration.
A transfer event requires exact paired pre/post valuations; real evidence
would need independent review of identity, timing and completeness.
"""
from datetime import datetime,timezone,timedelta
from decimal import Decimal,localcontext,ROUND_CEILING
from fractions import Fraction
from tradebot.m20_subaccount_equity_v3 import number
from tradebot.equity_policy_reference_v3 import DEFAULT_LIMITS,ANCHOR_WINDOW,stamp

def equity_value(v):
    d=number(v)
    if d<Decimal("0.01") or d>Decimal("1000000000000"):
        raise ValueError("fixture_equity_outside_numeric_domain")
    if len(d.as_tuple().digits)>40 or d.as_tuple().exponent < -18:
        raise ValueError("fixture_precision_outside_domain")
    return Fraction(d)

def loss_text(x):
    with localcontext() as ctx:
        ctx.prec=40
        ctx.rounding=ROUND_CEILING
        return str(Decimal(x.numerator)/Decimal(x.denominator))

def study(fixture):
    if fixture.get("mode")!="synthetic_policy_research" or fixture.get("execution_authorized") is not False:
        raise ValueError("synthetic_only")
    s=fixture["symbol"];identity=fixture["fixture_account"]
    if s not in ("BTCUSD","XAUTUSD") or not isinstance(identity,str) or not identity:
        raise ValueError("account_scope")
    out=dict(mode="synthetic_policy_comparison_only",symbol=s,
             execution_authorized=False,orders_submitted=0,policy_deployed=False,
             historical_anchor_created=False,broker_evidence_verified=False)
    if fixture.get("complete_fixture") is not True:
        return dict(out,status="missing_fixture_evidence")
    events=fixture["events"]
    if not isinstance(events,list) or not 1<=len(events)<=10000:
        raise ValueError("event_count")
    samples=[];ids=set();last=None;equity=None;index=Fraction(1);peak=index
    with localcontext() as ctx:
        ctx.prec=40
        for event in events:
            if event["symbol"]!=s or event["fixture_account"]!=identity:
                raise ValueError("cross_account")
            t=event["at_us"];key=event["event_id"]
            if type(t) is not int or t<=0 or (last is not None and t<=last):
                raise ValueError("event_order")
            if not isinstance(key,str) or not key or key in ids:
                raise ValueError("duplicate_event")
            ids.add(key);kind=event["kind"]
            if kind=="valuation":
                v=equity_value(event["equity"])
                if v<=0:raise ValueError("positive_equity_required")
                if equity is not None:index*=v/equity
                equity=v
            elif kind=="capital":
                if equity is None:raise ValueError("missing_prior_valuation")
                before=equity_value(event["before"]);after=equity_value(event["after"]);flow=number(event["flow"])
                if before<=0 or after<=0 or not flow or after-before!=flow:
                    raise ValueError("unmatched_capital_valuation")
                index*=before/equity
                peak=max(peak,index)
                equity=after
            else:raise ValueError("unknown_event")
            if max(index.numerator.bit_length(),index.denominator.bit_length())>16384:raise ValueError("fixture_index_precision_budget")
            peak=max(peak,index);samples.append((t,index,kind));last=t
        at=datetime.fromtimestamp(last/1000000,timezone.utc)
        day=at.replace(hour=0,minute=0,second=0,microsecond=0)
        week=day-timedelta(days=day.weekday())
        loss=lambda ref:loss_text(max(Fraction(0),Fraction(1)-index/ref))
        out.update(status="fixture_calculated",index=loss_text(index),
                   observed_peak_decline=loss(peak),daily_decline=None,weekly_decline=None,
                   daily_reference="missing",weekly_reference="missing",
                   reference_scope="observed_fixture_only",
                   exact_fraction_arithmetic=True,loss_rounding="upward",
                   unsampled_intraperiod_peaks_verified=False,
                   comparison_thresholds=[str(x) for x in DEFAULT_LIMITS])
        for label,start in (("daily",day),("weekly",week)):
            t0=stamp(start)
            anchor=next((v for t,v,k in samples if k=="valuation" and t0<=t<t0+ANCHOR_WINDOW*1000000),None)
            if anchor is not None:
                out[label+"_decline"]=loss(anchor)
                out[label+"_reference"]="fixture_opening_observation"
        return out
