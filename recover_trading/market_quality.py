"""Observation-only feed freshness and recent demo candle quality."""
import json,sqlite3
from contextlib import closing
from pathlib import Path
from tradebot.market_data_v3 import FRAMES
from .price_audit import audit

def diagnostics(report,path):
    now=report["as_of"]; cutoff=report.get("candle_as_of",now)
    if type(now) is not int or type(cutoff) is not int or not 0<cutoff<=now:
        raise ValueError("invalid observation cutoff")
    context=report.get("market_context",{})
    health=report.get("feed_health",{})
    frames={}
    for frame,step in FRAMES.items():
        row=context.get("frames",{}).get(frame,{})
        closed=row.get("closed_at")
        expected=cutoff//step*step
        latest=now//step*step
        ready=row.get("status")=="ready" and type(closed) is int
        frames[frame]={"snapshot_status":row.get("status","unavailable"),
                       "collection_status":health.get("candle:"+frame,{}).get("status","unknown"),
                       "collection_reason":health.get("candle:"+frame,{}).get("reason"),
                       "closed_at":closed if ready else None,
                       "expected_at_scan":expected,
                       "expected_at_observation":latest,
                       "lag_at_scan_s":expected-closed if ready else None,
                       "lag_at_observation_s":latest-closed if ready else None}
    quotes={}
    for name in ("ticker","book","flow","xau_reference"):
        q=context.get("quotes",{}).get(name)
        stamp=q.get("timestamp_us") if isinstance(q,dict) else None
        quotes[name]={"age_s":round((now*1000000-stamp)/1000000,3) if type(stamp) is int else None,
                      "collection_status":health.get(name,{}).get("status","unknown")}
    recent=None
    if Path(path).is_file():
        end=cutoff//300*300
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            bars=[json.loads(x[0]) for x in db.execute(
              "SELECT payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<? ORDER BY stamp",
              (report["symbol"],end-86400,end))]
        a=audit(bars)
        recent={"source":"demo","end":end,"expected_rows":288,"rows":a["rows"],
                "opening_gaps_gt_1pct":a["gap_count"],"ranges_gt_2pct":a["range_count"]}
    return {"version":"market-quality-v1","execution_effect":"none","as_of":now,"scan_cutoff":cutoff,
            "scan_age_s":now-cutoff,"frames":frames,"quotes":quotes,
            "recent_24h":recent,"feed_health":health}
