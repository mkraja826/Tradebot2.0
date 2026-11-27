"""Prospective Gold V2 research journal. No broker or automatic learning writes."""
import json
import sqlite3
import time
from collections import defaultdict, Counter
from math import isfinite
from .gold_v2_replay import outcome
from .gold_v2_stops import compare as compare_stops
from .gold_v2_scaling import compare as compare_scaling, VERSION as SIZING_VERSION

VERSION="gold-v2-validation.3"
HORIZON=12
COSTS=(5,15,30)
STEP=300
TARGET=1000

def encode(value):
    return json.dumps(value,sort_keys=True,allow_nan=False,separators=(",",":"))

def valid_number(value):
    return type(value) in (int,float) and isfinite(value)

class Journal:
    def __init__(self,path,*,clock=time.time):
        self.db=sqlite3.connect(path,timeout=10)
        self.db.row_factory=sqlite3.Row
        self.clock=clock
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS gold_v2_windows (
            signal_boundary INTEGER PRIMARY KEY, enrolled_at REAL NOT NULL,
            entry_boundary INTEGER, end_boundary INTEGER,
            status TEXT NOT NULL, evidence TEXT NOT NULL,
            policy_version TEXT NOT NULL, outcome_json TEXT, resolved_at REAL
        );
        """)
    def close(self):
        self.db.close()

    def enroll(self,report):
        if report.get("symbol")!="XAUTUSD":
            raise ValueError("wrong_symbol")
        signal=report.get("as_of")
        decision=report.get("decision_as_of",signal)
        now=self.clock()
        if not all(valid_number(x) for x in (signal,decision,now)):
            raise ValueError("invalid_time")
        # No historical backfill enrollment, and no entry before evidence existed.
        if not 0<=now-decision<=120 or not 0<=decision-signal<300:
            raise ValueError("nonprospective_observation")
        boundary=int(signal)//STEP*STEP
        if int(now)//STEP*STEP!=boundary:
            raise ValueError("expired_signal_window")
        candidates=report.get("candidates",[])
        pairs=[]
        for c in candidates:
            key=(c.get("family"),c.get("direction"))
            if not isinstance(key[0],str) or key[1] not in ("LONG","SHORT") or key in pairs:
                raise ValueError("invalid_or_duplicate_candidate")
            if not all(valid_number(c.get(k)) and c[k]>0 for k in
                       ("atr","stop_distance_atr_hypothesis","target_distance_atr_hypothesis")):
                raise ValueError("invalid_candidate_distances")
            pairs.append(key)
        status="enrolled" if report.get("status")=="observed" and candidates else "no_candidate" if report.get("status")=="observed" else "unusable"
        entry=(int(now)//STEP+1)*STEP
        end=entry+HORIZON*STEP
        evidence=encode(report)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing=self.db.execute("SELECT status FROM gold_v2_windows WHERE signal_boundary=?",(boundary,)).fetchone()
            if existing:
                return {"status":"duplicate","original_status":existing["status"],"signal_boundary":boundary}
            if status=="enrolled":
                overlaps=self.db.execute("""SELECT 1 FROM gold_v2_windows
                    WHERE entry_boundary < ? AND end_boundary > ?
                    AND status IN ('enrolled','resolved') LIMIT 1""",(end,entry)).fetchone()
                if overlaps: status="overlap_excluded"
            self.db.execute("INSERT INTO gold_v2_windows VALUES (?,?,?,?,?,?,?,NULL,NULL)",
               (boundary,now,entry if candidates else None,end if candidates else None,status,evidence,VERSION))
        return {"status":status,"signal_boundary":boundary,"entry_boundary":entry if status=="enrolled" else None}

    def resolve(self,bars):
        """Resolve only complete elapsed windows, once. Input is closed 5m bars."""
        now=self.clock()
        closed={}
        for b in bars:
            if type(b.ts) is not int or b.ts%STEP or b.ts>now or b.ts in closed:
                raise ValueError("invalid_resolution_bars")
            closed[b.ts]=b
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            rows=self.db.execute("SELECT * FROM gold_v2_windows WHERE status='enrolled' AND end_boundary<=? ORDER BY signal_boundary",(now,)).fetchall()
            count=0
            for row in rows:
                expected=range(row["entry_boundary"]+STEP,row["end_boundary"]+STEP,STEP)
                if any(t not in closed for t in expected):
                    # Allow delayed collection until 24 hours after the horizon.
                    if now-row["end_boundary"]<86400: continue
                    result={"status":"missing_window","candidates":[]}
                else:
                    report=json.loads(row["evidence"])
                    future=[closed[t] for t in expected]
                    samples=[]
                    for c in report["candidates"]:
                        scenarios={str(cost):outcome(c,future,as_of=row["entry_boundary"],
                                   horizon=HORIZON,cost_bps=cost) for cost in COSTS}
                        sample={"family":c["family"],"direction":c["direction"],"scenarios":scenarios}
                        if row["policy_version"] in ("gold-v2-validation.2","gold-v2-validation.3"):
                            sample["sizing"]={str(cost):compare_scaling(c,future,as_of=row["entry_boundary"],horizon=HORIZON,cost_bps=cost) for cost in COSTS}
                        if row["policy_version"]=="gold-v2-validation.3":
                            ema=report.get("features",{}).get("300",{}).get("ema",[])
                            stop_candidate=dict(c,entry_ema9=ema[0] if ema else None)
                            sample["stops"]={str(cost):compare_stops(stop_candidate,future,as_of=row["entry_boundary"],horizon=HORIZON,cost_bps=cost) for cost in COSTS}
                        samples.append(sample)
                    result={"status":"evaluated","candidates":samples}
                self.db.execute("UPDATE gold_v2_windows SET status='resolved',outcome_json=?,resolved_at=? WHERE signal_boundary=? AND status='enrolled'",
                                (encode(result),now,row["signal_boundary"]))
                count+=1
        return count

    def summary(self):
        rows=self.db.execute("SELECT * FROM gold_v2_windows ORDER BY signal_boundary").fetchall()
        states=Counter(r["status"] for r in rows)
        groups=defaultdict(list)
        exclusions=Counter()
        sizing_groups=defaultdict(list)
        stop_groups=defaultdict(list)
        stop_exclusions=Counter()
        observed_windows=0
        for row in rows:
            if row["status"]!="resolved": continue
            evidence=json.loads(row["evidence"])
            result=json.loads(row["outcome_json"])
            if result["status"]!="evaluated":
                exclusions[result["status"]]+=1
                continue
            scored={(c["family"],c["direction"]):c for c in evidence.get("intelligence",{}).get("candidates",[])}
            any_valid=False
            for c in result["candidates"]:
                s=scored.get((c["family"],c["direction"]),{})
                for cost,packet in c.get("sizing",{}).items():
                    baseline=packet["results"]["fixed"]
                    if baseline["status"]!="observed": continue
                    for policy,variant in packet["results"].items():
                        if policy=="fixed" or variant["status"]!="observed": continue
                        key=(evidence.get("version","unknown"),packet["version"],c["family"],c["direction"],cost,policy)
                        sizing_groups[key].append((baseline["net_bps_initial_notional"],variant["net_bps_initial_notional"],variant["peak_quantity_units"]))
                for cost,packet in c.get("stops",{}).items():
                    baseline=packet["results"]["fixed"]
                    for policy,variant in packet["results"].items():
                        if policy=="fixed":continue
                        if baseline["status"]!="observed" or variant["status"]!="observed":
                            stop_exclusions[policy+":"+cost+":"+baseline["status"]+":"+variant["status"]]+=1
                            continue
                        key=(evidence.get("version","unknown"),packet["version"],c["family"],c["direction"],cost,policy)
                        stop_groups[key].append((baseline["net_bps"],variant["net_bps"],len(variant["stop_changes"])))
                for cost,scenario in c["scenarios"].items():
                    if scenario["status"]!="observed":
                        exclusions[cost+":"+scenario["status"]]+=1
                        continue
                    any_valid=True
                    key=(evidence.get("version","unknown"),evidence.get("intelligence",{}).get("version","unknown"),
                         c["family"],c["direction"],s.get("support_index"),s.get("observed_groups"),cost)
                    groups[key].append(scenario["net_bps"])
            observed_windows+=int(any_valid)
        stats=[]
        for (engine,scoring,family,direction,index,coverage,cost),v in groups.items():
            stats.append({"engine_version":engine,"score_version":scoring,"family":family,"direction":direction,
                          "support_index":index,"observed_groups":coverage,"cost_bps":int(cost),
                          "samples":len(v),"mean_net_bps":sum(v)/len(v),
                          "positive_rate":sum(x>0 for x in v)/len(v)})
        sizing_stats=[]
        for (engine,version,family,direction,cost,policy),v in sizing_groups.items():
            sizing_stats.append({"engine_version":engine,"sizing_version":version,"family":family,"direction":direction,
                "cost_bps":int(cost),"policy":policy,"paired_samples":len(v),
                "mean_fixed_net_bps_initial_notional":sum(x[0] for x in v)/len(v),
                "mean_variant_net_bps_initial_notional":sum(x[1] for x in v)/len(v),
                "mean_paired_difference_bps":sum(x[1]-x[0] for x in v)/len(v),
                "max_peak_quantity_units":max(x[2] for x in v)})
        stop_stats=[]
        for (engine,version,family,direction,cost,policy),v in stop_groups.items():
            stop_stats.append({"engine_version":engine,"stop_version":version,"family":family,"direction":direction,
                "cost_bps":int(cost),"policy":policy,"paired_samples":len(v),
                "mean_fixed_net_bps":sum(x[0] for x in v)/len(v),
                "mean_variant_net_bps":sum(x[1] for x in v)/len(v),
                "mean_paired_difference_bps":sum(x[1]-x[0] for x in v)/len(v),
                "mean_stop_changes":sum(x[2] for x in v)/len(v)})
        return {"version":VERSION,"execution_effect":"none","window_counts":dict(states),
                "stop_comparisons":stop_stats,"stop_exclusions":dict(stop_exclusions),
                "sizing_comparisons":sizing_stats,
                "observed_nonoverlapping_windows":observed_windows,"target_windows":TARGET,
                "target_reached":observed_windows>=TARGET,"exclusions":dict(exclusions),
                "groups":stats,"note":"hypothetical outcomes, correlated same-window candidates; no automatic promotion"}
