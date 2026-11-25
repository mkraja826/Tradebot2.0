"""Read-only strategy lab catalogue, with explicit limits on current-state evidence."""
from .direction import REGISTRY
from .regime import FAMILIES

VERSION="strategy-lab-v1"
def build(symbol,heartbeat,evidence,deferred,now):
    registry,waiting=REGISTRY[symbol]
    implemented={r.id:r for r in registry}
    h=heartbeat or {};d=h.get("direction_engine") or {};c=h.get("coverage") or {}
    observed=h.get("timestamp")
    groups=d.get("votes")
    fresh=type(observed) is int and 0<=now-observed<=180 and h.get("status") not in ("cycle_error","scan_error") and isinstance(groups,dict) and all(isinstance(groups.get(k),list) for k in ("LONG","SHORT","CONFLICT"))
    votes={}
    if fresh:
        for side in ("LONG","SHORT","CONFLICT"):
            for r in groups[side]:
                if not isinstance(r,dict) or r.get("id") not in implemented:continue
                i=r["id"]
                if i in votes and votes[i][0]!=side:votes[i]=("CONFLICT",[])
                else:votes[i]=(side,r.get("frames") or [])
    fully_evaluable=fresh and c.get("evaluable_rules")==len(implemented) and c.get("unavailable_rules")==0
    by={r["id"]:r for r in (evidence or {}).get("rules",[])}
    research={r["id"]:r for r in (deferred or {}).get("rules",[])}
    result=[]
    for i in sorted(set(implemented)|set(waiting)):
        r=implemented.get(i);ev=by.get(i,{})
        state,frames=votes.get(i,("inactive" if fully_evaluable else "no_vote_unverified" if fresh else "stale_or_unavailable",[]))
        if r is None:state="deferred"
        result.append({"id":i,"name":r.name if r else waiting[i][0],"family":FAMILIES[i],
            "implementation":"implemented" if r else "deferred","state":state,"active_frames":frames,
            "frames":list(r.frames) if r else [],"required_inputs":r.fields.split() if r else [],
            "missing_dependency":None if r else waiting[i][1],"deferred_evidence":research.get(i),
            "research":ev.get("research"),"actual_cooccurrence":ev.get("actual_cooccurrence")})
    return {"version":VERSION,"symbol":symbol,"observed":observed,"fresh":fresh,"evaluable_rules":c.get("evaluable_rules") if fresh else None,"rules":result,"research_status":(evidence or {}).get("status","unavailable"),"execution_effect":"none"}
