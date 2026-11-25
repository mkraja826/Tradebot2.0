"""Overlap-aware directional balance research, not a calibrated confidence probability."""
import json,math,sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from itertools import combinations
from .combination_intelligence import overlap,valid_rule,BUCKET
from .planner_shadow import VERSION as SOURCE_VERSION
from .regime import FAMILIES,weighted_votes

VERSION="overlap-confidence-v1"
MIN_TOGETHER=20
MIN_JACCARD=.8
MIN_AGREEMENT=.9
LOOKBACK=288
REPLAY_BUCKETS=24
SIDES=("LONG","SHORT","CONFLICT")

def groups_for(symbol,p):
    if p.get("symbol")!=symbol or p.get("version")!=SOURCE_VERSION or type(p.get("as_of")) is not int or p["as_of"]<=0:return None
    a=p.get("active_rules")
    if not isinstance(a,dict) or any(not isinstance(a.get(k),list) for k in SIDES):return None
    if any(not valid_rule(symbol,r) for k in SIDES for r in a[k]):return None
    groups={k:sorted(set(a[k])) for k in SIDES}
    if any(set(groups[x])&set(groups[y]) for x,y in combinations(SIDES,2)):return None
    return groups

def eligible_pairs(history):
    return {tuple(r["rules"]) for r in history["pairs"] if r["together"]>=MIN_TOGETHER and r["jaccard"]>=MIN_JACCARD
        and r["same_direction"]/r["together"]>=MIN_AGREEMENT}

def cluster(rules,edges):
    # Complete-link greedy grouping: a rule must overlap with EVERY member.
    # A-B and B-C alone are not evidence that A and C are interchangeable.
    out=[]
    for r in sorted(rules):
        target=next((g for g in out if all(tuple(sorted((r,x))) in edges for x in g)),None)
        if target is None:out.append([r])
        else:target.append(r)
    return out

def score(symbol,p,prior):
    g=groups_for(symbol,p);regime=p.get("regime") or {}
    out={"as_of":p.get("as_of"),"status":"unverified","execution_effect":"none"}
    if g is None or regime.get("regime") not in ("trending","ranging","mixed","unknown") or regime.get("volatility") not in ("normal","high","unknown"):return out
    bucket=p["as_of"]//BUCKET
    hist=overlap(symbol,[x for x in prior if type(x.get("as_of")) is int and bucket-LOOKBACK<=x["as_of"]//BUCKET<bucket])
    edges=eligible_pairs(hist)
    baseline,families=weighted_votes({k:[{"id":r} for r in g[k]] for k in SIDES},regime)
    baseline={k:v/100 for k,v in baseline.items()}
    def side(t):
        return "LONG" if t["LONG"]>t["SHORT"]+1e-9 else "SHORT" if t["SHORT"]>t["LONG"]+1e-9 else "NEUTRAL"
    recorded=p.get("scores") or {}
    if p.get("direction")!=side(baseline) or any(type(recorded.get(k.lower())) not in (int,float) or not math.isfinite(recorded[k.lower()]) or abs(recorded[k.lower()]-baseline[k])>1e-6 for k in baseline):
        out["status"]="baseline_reconstruction_mismatch";return out
    adjusted={};detail={}
    for k in baseline:
        contributions={r:families[FAMILIES[r]][k]["score"]/families[FAMILIES[r]][k]["count"] for r in g[k]}
        clusters=cluster(g[k],edges)
        detail[k]=[{"rules":c,"families":sorted({FAMILIES[r] for r in c}),"original_contribution":sum(contributions[r] for r in c),
            "retained_contribution":max(contributions[r] for r in c)} for c in clusters]
        adjusted[k]=sum(r["retained_contribution"] for r in detail[k])
    def balance(t):
        total=sum(t.values())
        return abs(t["LONG"]-t["SHORT"])/total if total else None
    out.update(status="observed",baseline_direction=side(baseline),research_direction=side(adjusted),direction_changed=side(baseline)!=side(adjusted),
        baseline_scores=baseline,research_scores=adjusted,baseline_balance=balance(baseline),research_balance=balance(adjusted),
        history_snapshots=hist["sampled_packets"],eligible_overlap_pairs=len(edges),conflict_rules=g["CONFLICT"],clusters=detail,
        discounted_rule_count=sum(len(c["rules"])-1 for k in detail for c in detail[k]))
    return out

def build(symbol,packets):
    valid=[p for p in packets if groups_for(symbol,p) is not None]
    valid.sort(key=lambda p:p["as_of"])
    sampled={}
    for p in valid:sampled.setdefault(p["as_of"]//BUCKET,p)
    rows=list(sampled.values())
    replay=[score(symbol,p,rows) for p in rows[-REPLAY_BUCKETS:]]
    latest=score(symbol,valid[-1],rows) if valid else None
    checked=[r for r in replay if r["status"]=="observed"]
    return {"version":VERSION,"symbol":symbol,"status":"observed" if latest else "no_packets","execution_effect":"none","validation":"retrospective_diagnostic_only",
        "protocol":{"lookback_buckets":LOOKBACK,"bucket_s":BUCKET,"minimum_coactivations":MIN_TOGETHER,"minimum_jaccard":MIN_JACCARD,"minimum_same_direction_fraction":MIN_AGREEMENT,"replay_buckets":REPLAY_BUCKETS},
        "latest":latest,"replay":replay,"replay_counts":{"evaluated":len(checked),"direction_changes":sum(r["direction_changed"] for r in checked),"discount_applied":sum(r["discounted_rule_count"]>0 for r in checked),"unverified":len(replay)-len(checked)},
        "limitations":["Overlap measures co-activation, not return correlation or statistical independence.",
        "Scores are relative directional balance, not confidence probabilities or expected profit. Lower score does not imply worse trade.",
        "Historical packet observation time, not proven journal commit time, determines prior data; no future observation bucket used. This is retrospective, not frozen prospective evidence.",
        "Uncalibrated thresholds and complete-link clustering are research choices; no live weights, AI feedback or trading changes."]}

def report(root,symbol):
    try:
        with closing(sqlite3.connect((Path(root)/"planner_shadow.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            # Bound report work to the lookback plus replay and a small boundary buffer.
            end=db.execute("SELECT max(as_of) FROM planner_packets WHERE symbol=? AND version=?",(symbol,SOURCE_VERSION)).fetchone()[0]
            packets=[json.loads(r) for r, in db.execute("SELECT payload FROM planner_packets WHERE symbol=? AND version=? AND as_of>=? ORDER BY as_of",(symbol,SOURCE_VERSION,(end or 0)-(LOOKBACK+REPLAY_BUCKETS+2)*BUCKET))]
        return build(symbol,packets)
    except (sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,ArithmeticError):
        return {"version":VERSION,"symbol":symbol,"status":"unavailable","execution_effect":"none"}
