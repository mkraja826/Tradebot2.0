"""Frozen, offline planner input pairs. No provider or broker invocation."""
import argparse,hashlib,json,sqlite3,time
from pathlib import Path
from contextlib import closing
from collections import Counter
from .direction import compact_context
from .reference_strategy import VERSION as REFERENCE_VERSION
from .planner_shadow import VERSION as PLANNER_VERSION
from tradebot.market_data_v3 import MARKETS

VERSION="planner-comparison-v1"
MAX_AGE=1200
def encode(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)
def digest(x):
    return hashlib.sha256(encode(x).encode()).hexdigest()
def readonly(p):
    return sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)

def make_pair(symbol,ident,model,created,context,reference,planner):
    at=context.get("as_of")
    if context.get("symbol")!=symbol or type(at) is not int or type(created) is not int or at>created+1:
        raise ValueError("invalid decision identity")
    # Use strictly earlier, completed reference reports. Completion is a
    # recorded timestamp, not proof that the old provider actually saw it.
    evidence={}
    if isinstance(reference,dict) and reference.get("symbol")==symbol and reference.get("version")==REFERENCE_VERSION:
        g,c,t=(reference.get(k) for k in ("generated","completed","as_of"))
        if all(type(x) is int for x in (g,c,t)) and 0<t<=g<=c<min(at,created) and 0<at-c<=MAX_AGE and 0<=at-t<=MAX_AGE:
            evidence["reference"]={k:reference[k] for k in ("as_of","generated","completed","comparable_rule_frames","comparison_counts","matched_demo","matched_reference","coverage") if k in reference}
    if isinstance(planner,dict) and planner.get("symbol")==symbol and planner.get("version")==PLANNER_VERSION:
        t=planner.get("as_of")
        # Planner journal lacks a committed-at timestamp: use strictly
        # earlier observation time and disclose that limitation.
        if type(t) is int and 0<at-t<=MAX_AGE and t<created:
            evidence["planner"]={k:planner[k] for k in ("as_of","direction","regime","scores","active_rules","opportunity","reference_research") if k in planner}
    base=compact_context(context)
    enhanced={**base,"experimental_reference_evidence":evidence,
        "experimental_note":"Research context only. Reference market prices are not executable demo prices. Retain the original demo direction; never treat historical statistics as probabilities."}
    return {"version":VERSION,"symbol":symbol,"decision_id":ident,"model":model,"created":created,"as_of":at,
            "baseline":base,"alternative":enhanced,"baseline_sha256":digest(base),"alternative_sha256":digest(enhanced),
            "evidence_status":"reference_and_planner" if len(evidence)==2 else "reference_only" if "reference" in evidence else "planner_only" if "planner" in evidence else "unavailable",
            "baseline_bytes":len(encode(base).encode()),"alternative_bytes":len(encode(enhanced).encode()),
            "status":"inputs_prepared","experimental_proposals":0,"execution_effect":"none"}

def earlier(root,symbol,at,created):
    reference=planner=None
    if (root/"reference_strategy.sqlite").exists():
        with closing(readonly(root/"reference_strategy.sqlite")) as db:
            for raw, in db.execute("SELECT payload FROM comparisons WHERE symbol=? AND generated<? ORDER BY generated DESC LIMIT 10",(symbol,min(at,created))):
                p=json.loads(raw)
                if type(p.get("completed")) is int and p["completed"]<min(at,created):
                    reference=p;break
    if (root/"planner_shadow.sqlite").exists():
        with closing(readonly(root/"planner_shadow.sqlite")) as db:
            row=db.execute("SELECT payload FROM planner_packets WHERE symbol=? AND version=? AND as_of<? ORDER BY as_of DESC LIMIT 1",(symbol,PLANNER_VERSION,min(at,created))).fetchone()
            if row:planner=json.loads(row[0])
    return reference,planner

def run(root,symbol,now):
    root=Path(root)/symbol
    with closing(sqlite3.connect(root/"planner_comparison.sqlite",timeout=5)) as db:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS protocol(id INTEGER PRIMARY KEY CHECK(id=1),start INTEGER NOT NULL,version TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO protocol VALUES(1,?,?)",(now,VERSION))
            start,version=db.execute("SELECT start,version FROM protocol WHERE id=1").fetchone()
            if version!=VERSION:raise ValueError("protocol mismatch")
            db.execute("CREATE TABLE IF NOT EXISTS pairs(decision_id TEXT PRIMARY KEY,created INTEGER NOT NULL,payload TEXT NOT NULL)")
        source=root/"decisions.sqlite"
        preview=None
        if source.exists():
            with closing(readonly(source)) as src:
                # Pre-start records are only a dry-run diagnostic, never enrolled.
                fresh=src.execute("SELECT id,model,created,context FROM decisions WHERE symbol=? AND created>=? AND created<=? ORDER BY created,rowid",(symbol,start,now)).fetchall()
                last=src.execute("SELECT id,model,created,context FROM decisions WHERE symbol=? AND created<? ORDER BY created DESC,rowid DESC LIMIT 1",(symbol,start)).fetchone()
            def build(row):
                ident,model,created,raw=row;context=json.loads(raw)
                ref,planner=earlier(root,symbol,context["as_of"],created)
                return make_pair(symbol,ident,model,created,context,ref,planner)
            if last:
                p=build(last)
                preview={k:p[k] for k in ("evidence_status","baseline_bytes","alternative_bytes","as_of")}
            with db:
                for row in fresh:
                    if not db.execute("SELECT 1 FROM pairs WHERE decision_id=?",(row[0],)).fetchone():
                        p=build(row)
                        db.execute("INSERT INTO pairs VALUES(?,?,?)",(row[0],row[2],encode(p)))
        rows=[json.loads(r[0]) for r in db.execute("SELECT payload FROM pairs ORDER BY created")]
        latest={k:rows[-1][k] for k in ("created","as_of","evidence_status","baseline_bytes","alternative_bytes")} if rows else None
        result={"version":VERSION,"symbol":symbol,"start":start,"generated":now,
                "prepared_pairs":len(rows),"evidence_counts":dict(Counter(x["evidence_status"] for x in rows)),
                "latest":latest,"retrospective_input_preview":preview,"experimental_proposals":0,"execution_effect":"none",
                "limitations":["Input preparation only; no AI proposals evaluated.",
                  "Baseline is reconstructed from archived context using current compaction, not a captured historical API body.",
                  "Reference reports must have completed strictly before decision context; planner observation time is not journal commit time.",
                  "No changes to original decisions, orders or AI provider."]}
    tmp=root/"planner_comparison.tmp";tmp.write_text(encode(result)+"\n");tmp.replace(root/"planner_comparison.json")
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",required=True);a=p.parse_args()
    failures=0
    for s in MARKETS:
        try:print(encode(run(a.data_dir,s,int(time.time()))),flush=True)
        except Exception as exc:
            failures+=1;print(encode({"symbol":s,"error":type(exc).__name__}),flush=True)
    return int(bool(failures))
if __name__=="__main__":raise SystemExit(main())
