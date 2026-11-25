"""Descriptive price anomaly audit and aligned outcome correlations; offline only."""
import math
import statistics
from collections import defaultdict
from bisect import bisect_left,bisect_right

def audit(bars,*,gap_pct=1,range_pct=2):
    gaps=[]; ranges=[]
    for i,b in enumerate(bars):
        span=(b["high"]/b["low"]-1)*100
        if span>range_pct: ranges.append((b["time"],span))
        if i and b["time"]-bars[i-1]["time"]==300:
            gap=abs(b["open"]/bars[i-1]["close"]-1)*100
            if gap>gap_pct:gaps.append((b["time"],gap))
    return {"rows":len(bars),"min_low":min((x["low"] for x in bars),default=None),
            "max_high":max((x["high"] for x in bars),default=None),
            "gap_threshold_pct":gap_pct,"range_threshold_pct":range_pct,
            "gap_count":len(gaps),"range_count":len(ranges),
            "largest_gaps":sorted(gaps,key=lambda x:-x[1])[:5],
            "largest_ranges":sorted(ranges,key=lambda x:-x[1])[:5],
            "flagged_timestamps":sorted({x[0] for x in gaps+ranges})}
def affected_events(events,flagged,*,partition="holdout"):
    """Flags outcome windows, not upstream indicator warmup contamination."""
    times=sorted(set(flagged)); counts=defaultdict(lambda:[0,0])
    for e in events:
        if e["partition"]!=partition: continue
        row=counts[(e["rule_id"],e["horizon_s"])]
        row[0]+=1
        if bisect_right(times,e["exit_at"])>bisect_left(times,e["entry_at"]):row[1]+=1
    return [{"rule_id":k[0],"horizon_s":k[1],"samples":v[0],"flagged_windows":v[1]} for k,v in sorted(counts.items())]
def correlations(events,*,horizon=3600,partition="development",minimum=20):
    """Pearson correlation of signed gross returns at identical decision times.
    Not a signal-activation correlation; pairs are conditional on co-occurrence.
    """
    groups=defaultdict(dict)
    for e in events:
        if e["partition"]==partition and e["horizon_s"]==horizon and not e["rule_id"].startswith("ensemble_"):
            groups[e["rule_id"]][e["decision_at"]]=e["gross_bps"]
    out=[]
    ids=sorted(groups)
    for i,a in enumerate(ids):
        for b in ids[i+1:]:
            common=sorted(groups[a].keys()&groups[b].keys())
            if len(common)<minimum:continue
            x=[groups[a][t] for t in common]; y=[groups[b][t] for t in common]
            if len(set(x))<2 or len(set(y))<2:continue
            corr=statistics.correlation(x,y)
            if math.isfinite(corr):out.append({"a":a,"b":b,"samples":len(common),"correlation":corr})
    return sorted(out,key=lambda x:-abs(x["correlation"]))
