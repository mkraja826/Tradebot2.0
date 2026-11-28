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


def read_hybrid_status(directory,now,*,packet=None):
    out={"status":"unavailable","execution_effect":"none"}
    try:
        if packet is None:
            with (Path(directory)/"hybrid_status.json").open("rb") as f:
                raw=f.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:return out
            packet=json.loads(raw)
        p=packet;stamp=number(p.get("timestamp"))
        if p.get("symbol")!="XAUTUSD" or p.get("mode")!="hybrid_research_only" or stamp is None or stamp>now:return out
        s=obj(p.get("summary"));signal=obj(p.get("latest_signal"));q=obj(signal.get("quote_comparison"))
        return dict(out,status="stale" if now-stamp>60 else "observed",age_seconds=now-stamp,
                    quote_record=label(p.get("quote_record")),quote_count=number(s.get("quote_count")),
                    outcome_count=number(s.get("outcome_count")),actual_fills=0,
                    reference_status=label(signal.get("reference_status")),hybrid_status=label(signal.get("hybrid_status")),
                    signal_observed_at=number(signal.get("signal_observed_at")),
                    window_counts={k:number(obj(s.get("window_counts")).get(k)) for k in
                        ("enrolled","not_enrolled","overlap_excluded","sampled_outcomes","insufficient_quote_coverage")},
                    quote_comparison={k:number(q.get(k)) for k in ("mark_basis_bps","book_basis_bps","quote_skew_ms","demo_spread_bps","reference_spread_bps")},
                    sampled_comparisons=[{**{k:label(r.get(k)) for k in ("family","direction")},
                        **{k:number(r.get(k)) for k in ("samples","positive_samples","mean_sampled_net_bps")}}
                        for r in rows(s.get("sampled_comparisons"),100)])
    except (OSError,ValueError,TypeError,AttributeError,OverflowError):return out


def read_mark_status(directory,now):
    """Separate mark cohort; never mistake a traded-price report for mark research."""
    out={"status":"unavailable","execution_effect":"none"}
    try:
        with (Path(directory)/"hybrid_status.json").open("rb") as f:
            raw=f.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:return out
        p=json.loads(raw)
        if p.get("signal_source")!="corroborated_production_mark":return out
        s=obj(p.get("summary"))
        if s.get("signal_source")!="corroborated_production_mark":return out
        base=read_hybrid_status(directory,now,packet=p)
        if base["status"]=="unavailable":return out
        signal=obj(p.get("latest_signal"));macro=obj(signal.get("macro_context"))
        base.update(signal_source="corroborated_production_mark",
            reference_quality={k:label(obj(obj(signal.get("reference_quality")).get(k)).get("status")) for k in ("300","900","3600")},
            macro={"status":label(macro.get("status")),"bias":label(macro.get("bias")),
                   "candidates":[{**{k:label(r.get(k)) for k in ("family","direction","macro_group")},
                                  **{k:number(r.get(k)) for k in ("support_index","observed_groups")}}
                                 for r in rows(macro.get("candidate_groups"),32)]},
            macro_strata=[{**{k:label(r.get(k)) for k in ("family","direction","model_version","macro_group")},
                           **{k:number(r.get(k)) for k in ("samples","positive_samples","mean_sampled_net_bps")}}
                          for r in rows(s.get("macro_strata"),200)],
            management_pairs=[{**{k:label(r.get(k)) for k in ("family","direction","model_version","management_version","policy")},
                               **{k:number(r.get(k)) for k in ("cost_bps","paired_samples","mean_fixed_net_bps","mean_variant_net_bps","mean_paired_difference_bps")}}
                              for r in rows(s.get("management_pairs"),200)])
        return base
    except (OSError,ValueError,TypeError,AttributeError,OverflowError):return out

def read_mark_learning(directory,now):
    out={"status":"unavailable","execution_effect":"none","automatic_promotion":False}
    try:
        with (Path(directory)/"mark_learning_status.json").open("rb") as f:
            raw=f.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:return out
        p=json.loads(raw)
        if p.get("version")!="gold-v2-mark-learning.1" or p.get("signal_source")!="corroborated_production_mark" or p.get("automatic_promotion") is not False:return out
        stamp=number(p.get("as_of"));cutoff=number(p.get("cutoff"))
        if stamp is None or cutoff is None or not 0<cutoff<stamp<=now:return out
        return dict(out,status="stale" if now-stamp>86400 else "observed",as_of=stamp,cutoff=cutoff,
                    proposals=[{**{k:label(r.get(k)) for k in ("model_version","family","direction","macro_group","selected_on_training","status")},
                                **{k:number(r.get(k)) for k in ("train_samples","holdout_samples")},
                                "holdout_net_bps_30":number(obj(obj(r.get("holdout_selected_only")).get("30")).get("mean_net_bps"))}
                               for r in rows(p.get("proposals"),200)])
    except (OSError,ValueError,TypeError,AttributeError,OverflowError):return out
