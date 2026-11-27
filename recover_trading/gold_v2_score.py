"""Gold V2 evidence fusion. Research scores are not probabilities or orders."""
from datetime import datetime, timezone
from math import isfinite

VERSION="gold-v2-score.1"

def numeric(x):
    return type(x) in (int,float) and isfinite(x)

def sign(x,band=0):
    if not numeric(x): return None
    return 1 if x>band else -1 if x<-band else 0

def frame_direction(report,seconds):
    frames=report.get("features",{})
    row=frames.get(seconds,frames.get(str(seconds),{}))
    d=row.get("direction")
    return d if type(d) is int and d in (-1,0,1) else None

def sessions(as_of):
    # UTC research windows, not exchange trading hours or holiday calendars.
    h=datetime.fromtimestamp(as_of,timezone.utc).hour
    return {"asia_utc_window":0<=h<9,"europe_utc_window":7<=h<16,
            "us_utc_window":13<=h<22,"definition":"fixed_utc_research_windows_not_dst_adjusted"}

def group(votes):
    known=[v for v in votes.values() if type(v) is int and v in (-1,0,1)]
    if len(known)!=len(votes):
        direction=None
    else:
        direction=sign(sum(known))
    return {"votes":votes,"observed":len(known),"expected":len(votes),
            "direction":direction}

def score(report):
    now=report.get("decision_as_of",report.get("as_of"))
    if report.get("symbol")!="XAUTUSD" or not numeric(now):
        raise ValueError("wrong_market_or_time")
    technical=group({str(s):frame_direction(report,s) for s in (300,900,3600)})
    fundamental=report.get("fundamentals",{})
    same_cutoff=fundamental.get("as_of")==now
    macro=fundamental.get("macro",{}) if same_cutoff else {}
    d=sign(macro.get("broad_dollar_5obs_pct"),0.2)
    y=sign(macro.get("real_yield_5obs_bp"),5)
    macro_group=group({"broad_dollar":None if d is None else -d,
                       "real_yield":None if y is None else -y})
    public=report.get("public_feeds",{})
    feeds=public.get("feeds",{}) if public.get("as_of")==now else {}
    def data(key):
        item=feeds.get(key,{})
        return item.get("data",{}) if item.get("status")=="observed" else {}
    cot=data("cot")
    # Weekly position change and price divergence are annotations, not extra votes.
    positioning={"net_change":cot.get("managed_money_net_change"),
                 "net_share":cot.get("managed_money_net_share"),
                 "report_date":cot.get("report_date"),"vote_used":False}
    extra=data("macro_extra").get("series",{})
    ratio=public.get("gold_silver_ratio") if public.get("as_of")==now else None
    spot=fundamental.get("spot_reference",{}) if same_cutoff else {}
    events=fundamental.get("events",{}) if same_cutoff else {}
    recent=[k for k,v in events.items() if v.get("status")=="observed" and v.get("recent_45m") is True]
    observed_events=[k for k,v in events.items() if v.get("status")=="observed"]
    result={"version":VERSION,"symbol":"XAUTUSD","as_of":now,
            "execution_effect":"none","score_semantics":"ordinal_hypothesis_not_probability",
            "technical":technical,"macro":macro_group,"positioning":positioning,
            "cross_market":{"gold_silver_ratio":ratio,"delta_spot_basis_bps":spot.get("basis_bps"),
               "paxg_usdt":data("paxg_usdt").get("price_usdt"),
               "xaut_usdt":data("xaut_usdt").get("price_usdt"),"vote_used":False},
            "macro_extra":extra,"events":{"recent":recent,"observed":observed_events,
               "missing":[k for k in ("fomc_release","cpi_release","nfp_release") if k not in observed_events]},
            "sessions":sessions(now),"candidates":[]}
    if report.get("status")!="observed":
        return dict(result,status="input_unusable")
    groups=(technical,macro_group)
    for c in report.get("candidates",[]):
        side={"LONG":1,"SHORT":-1}.get(c.get("direction"))
        if side is None: continue
        # Every group gets one equal vote. Unknown is separate from neutral.
        aligned=[None if g["direction"] is None else side*g["direction"] for g in groups]
        known=[v for v in aligned if v is not None]
        result["candidates"].append({"family":c["family"],"direction":c["direction"],
            "support_index":sum(known) if known else None,
            "observed_groups":len(known),"expected_groups":len(groups),
            "technical_alignment":aligned[0],"macro_alignment":aligned[1],
            "recent_event_context":recent,"conflicting_candidates":bool(report.get("conflicting_directions"))})
    return dict(result,status="observed")
