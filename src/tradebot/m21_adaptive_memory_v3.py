"""Bounded optional paper observations, never a strategy gate."""
import json,stat,os
from pathlib import Path
from math import isfinite
from statistics import mean
from collections import defaultdict
from tradebot.opportunity_journal_v3 import digest,ROUTE
from tradebot.regime_learning_v3 import classify

def unavailable(reason):
    return dict(status="unavailable",reason=reason,execution_authorized=False,strategy_eligibility_changed=False)

def freeze(root,symbol,signals,context,*,now):
    try:
        if symbol not in ROUTE or context["symbol"]!=symbol or context["context_observed_at"]!=now:
            return unavailable("context_mismatch")
        keys={(s["id"],s["frame"],s["direction"]):s for s in signals}
        if not keys:return unavailable("no_signal")
        p=Path(root)/"m21-paper-learning-v3.json"
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,"rb") as f:
            st=os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=2000000:raise ValueError()
            raw=f.read(2000001)
        if len(raw)>2000000:raise ValueError()
        r=json.loads(raw);t=r["checked_at"]
        if r["mode"]!="paper_learning_diagnostic_only" or r["execution_authorized"] is not False or r["orders_submitted"]!=0 or r["paid_ai_requests"]!=0 or r["verified_trade_outcomes"]!=0 or type(t) is not int or not 0<=now-t<=660 or len(r["records"])>20:
            return unavailable("invalid_or_stale_report")
        groups=defaultdict(dict)
        chosen=set(sorted(keys)[:12])
        for rec in r["records"]:
            if rec["symbol"]!=symbol:continue
            if rec["actual_trade_outcome"] is not False or rec["action"] not in ("WAIT","LONG","SHORT"):raise ValueError()
            for o in rec["signal_paths"]:
                k=(o["rule_id"],o["frame"],o["direction"])
                if k not in chosen or o["status"]!="observed":continue
                if o["symbol"]!=symbol or o["event_id"]!=rec["event_id"] or o["horizon_minutes"] not in (15,60,240) or not 0<o["reference_start"]<o["reference_end"]<=t:
                    raise ValueError()
                values=tuple(o[n] for n in ("directional_return_pct","favorable_excursion_pct","adverse_excursion_pct"))
                if any(type(x) not in (int,float) or not isfinite(x) for x in values):raise ValueError()
                regime=classify(context,keys[k])
                matched=sum(v!="unknown" and o["regime"].get(d)==v for d,v in regime.items())
                g=groups[(k,rec["action"],o["horizon_minutes"])]
                eid=rec["event_id"]
                item=(values,matched)
                if eid in g and g[eid]!=item:raise ValueError()
                g[eid]=item
        summaries=[]
        for (k,action,h),g in sorted(groups.items())[:36]:
            vals=list(g.values())
            summaries.append(dict(rule_id=k[0],frame=k[1],direction=k[2],previous_action=action,horizon_minutes=h,
                distinct_events=len(vals),sample_status="insufficient_sample" if len(vals)<30 else "descriptive_only",
                mean_signal_return_pct=mean(v[0][0] for v in vals),mean_favorable_excursion_pct=mean(v[0][1] for v in vals),
                mean_adverse_excursion_pct=mean(v[0][2] for v in vals),events_with_matching_regime=sum(v[1]>0 for v in vals)))
        return dict(status="research_advisory",source_checked_at=t,source_sha256=digest(r),matching_groups=summaries,
            warning="Paper model decisions with hypothetical accounts; overlapping signal paths are not fills, returns on trades, or model scores. Small samples; optional context only.",
            execution_authorized=False,strategy_eligibility_changed=False)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError):
        return unavailable("paper_memory_unavailable")
