"""Bounded local chart and strategy research projections."""
import json,time
from pathlib import Path
from contextlib import closing
from tradebot.decision_experience_v3 import ro
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
from tradebot.dashboard_analytics_v3 import select

def chart(root,symbol,frame,*,now=None):
    if symbol not in MARKETS or frame not in FRAMES:raise ValueError("invalid_chart_scope")
    now=int(time.time()) if now is None else now
    step=FRAMES[frame];boundary=now//step*step
    with closing(ro(Path(root)/"market-v3.sqlite")) as db:
        raw=db.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series=? AND stamp<? ORDER BY stamp DESC LIMIT 180",(symbol,"candle:"+frame,boundary)).fetchall()
    bars=[]
    for stamp,payload in reversed(raw):
        a=json.loads(payload)
        if a["time"]!=stamp:raise ValueError("timestamp_mismatch")
        bars.extend(normalize([a],frame,as_of=stamp+step,count=1))
    gaps=sum((b["time"]-a["time"])//step-1 for a,b in zip(bars,bars[1:]))
    return dict(symbol=symbol,frame=frame,step=step,bars=bars,gaps=gaps,checked_at=now,last_closed_at=bars[-1]["time"]+step if bars else None,execution_authorized=False)

def profiles(root,symbol,*,now=None):
    if symbol not in MARKETS:raise ValueError("invalid_scope")
    now=int(time.time()) if now is None else now
    p=Path(root)/"strategy-profiles-v3.json"
    if p.is_symlink():raise ValueError("invalid_file")
    with p.open("rb") as f:raw=f.read(8000001)
    if len(raw)>8000000:raise ValueError("oversized_file")
    r=json.loads(raw);t=r["checked_at"]
    if r["mode"]!="strategy_performance_advisory" or r["execution_authorized"] is not False or r["strategy_eligibility_changed"] is not False or type(t) is not int or not 0<=now-t:raise ValueError("invalid_report")
    out=[]
    for a in r["markets"][symbol]["profiles"][:100]:
        windows=[w for w in a["historical"] if 0<w["start"]<w["end"]<=t]
        latest=max(windows,key=lambda w:w["end"],default=None)
        if latest is None:continue
        for g in latest["scenarios"]:
            if g["scenario"]!="fixed" or g["horizon"]!=60 or g["frame"] not in FRAMES or g["side"] not in ("LONG","SHORT"):continue
            item=dict(rule_id=a["rule_id"],name=str(a["name"])[:100],start=latest["start"],end=latest["end"],**select(g,("frame","side","samples","sample_status")))
            item["costs"]={k:select(v,("mean_pct","positive","sequence_drawdown_pct_points")) for k,v in g["cost_scenarios"].items() if k in ("5","10","20")}
            out.append(item)
            if len(out)>2000:raise ValueError("oversize_rows")
    return dict(symbol=symbol,checked_at=t,age_seconds=now-t,state="fresh" if now-t<=660 else "historical",rows=out,execution_authorized=False,scope="latest_historical_window_fixed_60m_only")
