"""Bounded optional decision-time evidence, frozen with each shadow event."""
import json
from pathlib import Path
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.regime_learning_v3 import classify

def unavailable(reason):
    return {"status":"unavailable","reason":reason,"strategy_eligibility_changed":False,"execution_authorized":False}

def group(g,regime,forward=False):
    keys=("nonoverlapping_samples","observed","pending","missing") if forward else ("samples",)
    keys+=("sample_status","cost_scenarios","mean_favorable_excursion_pct","mean_adverse_excursion_pct")
    out={k:g[k] for k in keys if k in g}
    out["matching_regimes"]=[{k:r[k] for k in ("dimension","value","samples","mean_after_10bps_pct","positive_after_10bps","sample_status")}
        for r in g.get("regime_profiles",[]) if r["value"]!="unknown" and regime.get(r["dimension"])==r["value"]][:4]
    return out

def freeze(root,symbol,signals,context,*,now):
    if not signals: return unavailable("no_signal")
    try:
        p=Path(root)/"strategy-profiles-v3.json"
        if p.is_symlink() or p.stat().st_size>8_000_000: return unavailable("invalid_profile_file")
        report=json.loads(p.read_text())
        t=report["checked_at"]
        if report["mode"]!="strategy_performance_advisory" or report["execution_authorized"] is not False or report["strategy_eligibility_changed"] is not False or type(t) is not int or not 0<=now-t<=660: return unavailable("stale_or_invalid_profile")
        if context["symbol"]!=symbol or context["context_observed_at"]!=now: return unavailable("context_mismatch")
        profiles={x["rule_id"]:x for x in report["markets"][symbol]["profiles"]}
        keys={(x["id"],x["frame"],x["direction"]):x for x in signals}
        out=[]
        prefix={"BTCUSD":"B","XAUTUSD":"G"}[symbol]
        for (rule,frame,side),sig in sorted(keys.items())[:12]:
            if not rule.startswith(prefix) or side not in ("LONG","SHORT") or rule not in profiles or frame not in profiles[rule]["frames"]: continue
            x=profiles[rule]; regime=classify(context,sig)
            def match(g):
                return g["frame"]==frame and g["side"]==side and g["horizon"]==60
            hist=[]
            for w in x["historical"][:2]:
                if not 0<w["start"]<w["end"]<=t: continue
                hist.append({"start":w["start"],"end":w["end"],
                    "coverage":[{k:c[k] for k in ("evaluations","unavailable","no_signal","triggered") if k in c} for c in w["coverage"] if c["frame"]==frame][:1],
                    "fixed_60m":[group(g,regime) for g in w["scenarios"] if match(g) and g["scenario"]=="fixed"][:1]})
            out.append({"rule_id":rule,"frame":frame,"side":side,"signal_regime":regime,"historical":hist,
                "forward_shadow_60m":[group(g,regime,True) for g in x["forward_shadow"] if match(g)][:1]})
        result={"status":"research_advisory","profile_checked_at":t,"source_report_sha256":digest(report),
            "profiles":out,"signal_groups":len(keys),"omitted_signal_groups":len(keys)-len(out),
            "warning":"Hypothetical cost scenarios, not actual profitability. Historical and forward data are separate; small samples and correlated groups are not confidence estimates. Optional evidence only.",
            "strategy_eligibility_changed":False,"execution_authorized":False}
        if len(canonical(result))>60_000: return unavailable("oversize_advisory")
        return result
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError): return unavailable("profile_unavailable")
