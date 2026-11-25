"""Shadow AI evidence packet. No model request, proposal or execution side effects."""
import json,math,sqlite3
from pathlib import Path
from contextlib import closing
from .direction import REGISTRY
from .opportunity import opportunity

VERSION="planner-shadow-v1"
HORIZONS=(900,3600,14400)
def numeric(x):
    return x if type(x) in (int,float) and math.isfinite(x) else None

def research_summary(replay,calibration,*,built_at):
    if not replay.get("complete") or replay["symbol"]!=calibration["symbol"] or calibration["development_end_exclusive"]!=replay["split"]:
        raise ValueError("incompatible research sources")
    if type(built_at) is not int or built_at<replay["end"]:
        raise ValueError("invalid research availability")
    rules={r.id for r in REGISTRY[replay["symbol"]][0]}
    stats={}
    for r in replay["results"]:
        if r["partition"]=="development" and r["regime"]=="all" and r["rule_id"] in rules and r["horizon_s"] in HORIZONS:
            stats.setdefault(r["rule_id"],[]).append({k:r[k] for k in ("horizon_s","samples","mean_net_bps","mean_gross_bps","win_rate")})
    return {"version":"planner-reference-v1","symbol":replay["symbol"],"built_at":built_at,
            "dataset_end":replay["end"],"development_end":replay["split"],
            "stride_s":replay["stride_s"],"assumed_cost_bps":replay["cost_bps_round_trip"],
            "positive_training_candidates":calibration["positive_training_candidates"],"rules":stats,
            "validation":"exploratory_reference_research_not_independent"}

def packet(report,direction,reference=None):
    symbol,at=report["symbol"],report["as_of"]
    if symbol not in REGISTRY or type(at) is not int:raise ValueError("invalid market")
    active={k:[v["id"] for v in direction["votes"][k]] for k in ("LONG","SHORT","CONFLICT")}
    op=opportunity(report,direction)
    available=(isinstance(reference,dict) and reference.get("version")=="planner-reference-v1"
               and reference.get("symbol")==symbol and type(reference.get("built_at")) is int
               and type(reference.get("dataset_end")) is int and type(reference.get("development_end")) is int
               and 0<reference["development_end"]<=reference["dataset_end"]<=reference["built_at"]<=at)
    history={"status":"unavailable_at_decision"}
    if available:
        history={k:reference[k] for k in ("built_at","dataset_end","development_end","stride_s","assumed_cost_bps","positive_training_candidates","validation")}
        history["status"]="available"
        history["active_rule_development_stats"]={i:reference["rules"].get(i,[]) for i in sorted(set(active["LONG"]+active["SHORT"]))}
    return {"version":VERSION,"mode":"observation_only","symbol":symbol,"as_of":at,
            "direction":direction["direction"],"direction_version":direction["version"],
            "regime":direction["regime"],"scores":{"long":numeric(direction["long_score"]),"short":numeric(direction["short_score"])},
            "active_rules":active,"opportunity":op,"reference_research":history,
            "limitations":["Current observations are demo prices and may be distorted.",
              "Historical statistics use reference prices, estimated costs and fixed horizons.",
              "Historical results are descriptive, not a probability or trade recommendation.",
              "No AI proposal, weight change, order or additional model request."],
            "execution_effect":"none"}

def load_reference(path):
    p=Path(path)
    if not p.exists():return None
    with p.open("rb") as f:raw=f.read(131073)
    if len(raw)>131072:raise ValueError("oversized research summary")
    return json.loads(raw)

class ShadowJournal:
    def __init__(self,path):self.path=Path(path)
    def record(self,p):
        raw=json.dumps(p,sort_keys=True,separators=(",",":"),allow_nan=False)
        with closing(sqlite3.connect(self.path,timeout=2)) as db,db:
            db.execute("CREATE TABLE IF NOT EXISTS planner_packets (symbol TEXT NOT NULL, as_of INTEGER NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(symbol,as_of,version))")
            db.execute("INSERT OR IGNORE INTO planner_packets VALUES (?,?,?,?)",(p["symbol"],p["as_of"],p["version"],raw))
        return {"status":"recorded","version":p["version"],"reference_status":p["reference_research"]["status"],
                "packet_bytes":len(raw.encode()),"active_rules":sum(len(v) for v in p["active_rules"].values()),
                "execution_effect":"none"}
