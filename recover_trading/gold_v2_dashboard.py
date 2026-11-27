"""Read-only Gold V2 status projection. No exchange calls or journal mutations."""
import json
from math import isfinite
from pathlib import Path

VERSION="gold-v2-dashboard.1"
MAX_BYTES=512_000

def number(v):
    return v if type(v) in (int,float) and isfinite(v) else None

def label(v):
    return v[:100] if isinstance(v,str) else None

def obj(v):
    return v if isinstance(v,dict) else {}

def rows(v,limit):
    return [x for x in v[:limit] if isinstance(x,dict)] if isinstance(v,list) else []

def read_status(directory,now):
    out={"version":VERSION,"symbol":"XAUTUSD","status":"unavailable","execution_effect":"none"}
    try:
        with (Path(directory)/"gold_v2_status.json").open("rb") as f:
            raw=f.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:return out
        packet=json.loads(raw)
        if not isinstance(packet,dict) or packet.get("symbol")!="XAUTUSD":return out
        stamp=number(packet.get("timestamp"))
        if stamp is None or stamp>now:return out
        age=now-stamp
        market=obj(packet.get("market"));intel=obj(packet.get("intelligence"))
        macro=obj(intel.get("macro"));validation=obj(packet.get("validation"))
        tech={}
        for sec in ("300","900","3600"):
            frame=obj(obj(packet.get("technical")).get(sec))
            if not frame:continue
            ema=frame.get("ema")
            tech[sec]={k:number(frame.get(k)) for k in ("atr","direction","rsi14","adx","rolling_vwap20","relative_volume20")}
            tech[sec]["ema"]=[number(x) for x in ema[:4]] if isinstance(ema,list) else []
            tech[sec]["structure"]=label(frame.get("structure"))
        comparisons=[]
        for r in rows(validation.get("combined_comparisons"),200):
            comparisons.append({**{k:label(r.get(k)) for k in ("engine_version","combined_version","family","direction","policy")},
                                **{k:number(r.get(k)) for k in ("cost_bps","paired_samples","mean_fixed_net_bps_initial_notional","mean_variant_net_bps_initial_notional","mean_paired_difference_bps","max_peak_quantity_units","rejected_adds")}})
        account=obj(packet.get("account"));controller=obj(packet.get("controller"))
        out.update(status="stale" if age>180 else "observed",age_seconds=age,timestamp=stamp,
            worker_status=label(packet.get("status")),mode=label(packet.get("mode")),
            execution_enabled=packet.get("execution_enabled") if type(packet.get("execution_enabled")) is bool else None,
            market={k:label(market.get(k)) for k in ("version","status","regime")},
            feed_health={k:label(obj(market.get("feed_health")).get(k)) for k in ("5m","15m","1h")},
            technical=tech,macro={"bias":label(intel.get("macro_bias")),
                **{k:number(macro.get(k)) for k in ("broad_dollar_5obs_pct","real_yield_5obs_bp")}},
            candidates=[{**{k:label(c.get(k)) for k in ("family","direction")},
                         **{k:number(c.get(k)) for k in ("support_index","observed_groups","expected_groups")}}
                        for c in rows(intel.get("candidates") or packet.get("candidates"),32)],
            validation={**{k:number(validation.get(k)) for k in ("observed_nonoverlapping_windows","target_windows","combined_comparisons_total")},
                "combined_comparisons":comparisons},
            account={k:label(account.get(k)) for k in ("position_state","bracket_state")},
            controller={k:label(controller.get(k)) for k in ("status","execution_status","management_status")})
        return out
    except (OSError,ValueError,TypeError,OverflowError):
        return out
