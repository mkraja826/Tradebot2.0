"""Append-only synthetic decision memory. No broker or model transport."""
from pathlib import Path
from contextlib import closing
import json,sqlite3
from tradebot.opportunity_journal_v3 import canonical,digest,ROUTE
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.signal_learning_v3 import evaluate_event
from tradebot.research_collector_v3 import atomic_json

def project(event,receipt,symbol,event_id,*,now):
    if event["event_id"]!=event_id or event["symbol"]!=symbol or not 0<event["as_of"]<=now: raise ValueError("wrong_event")
    q=prepare(event); a=receipt["response"]
    if receipt["mode"]!="synthetic_wait_only" or receipt["execution_authorized"] is not False or receipt["request_sha256"]!=q["request_sha256"] or receipt["response_sha256"]!=digest(a) or a["action"]!="WAIT": raise ValueError("invalid_receipt")
    validate(a,q)
    exact="request" in receipt
    recorded=None
    if exact:
        stored=receipt["request"]; recorded=receipt["recorded_at"]
        if receipt["full_request_sha256"]!=digest(stored) or stored!=q or type(recorded) is not int or not event["as_of"]<=recorded<=min(now,event["as_of"]+150): raise ValueError("invalid_full_request")
    return {"mode":"synthetic_decision_experience","symbol":symbol,"event_id":event_id,
        "model_if_enabled":q["model_if_enabled"],"opportunity":event,"request":q,
        "request_provenance":"captured_at_dispatch" if exact else "reconstructed_payload_verified",
        "recorded_at":recorded,"receipt":receipt,"receipt_sha256":digest(receipt),
        "proposal_outcome":{"status":"not_applicable_wait"},"verified_broker_settlement":None,
        "actual_model_decision":False,"execution_authorized":False}

def ro(path):
    if path.is_symlink() or not path.is_file(): raise ValueError("untrusted_source")
    return sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)

def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS decisions(event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS observations(event_id TEXT NOT NULL,rule_id TEXT NOT NULL,frame TEXT NOT NULL,side TEXT NOT NULL,horizon INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(event_id,rule_id,frame,side,horizon),FOREIGN KEY(event_id) REFERENCES decisions(event_id));
    CREATE TABLE IF NOT EXISTS observation_errors(event_id TEXT PRIMARY KEY,reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS pending(event_id TEXT PRIMARY KEY,due INTEGER NOT NULL,FOREIGN KEY(event_id) REFERENCES decisions(event_id));
    CREATE TABLE IF NOT EXISTS cursor_state(id INTEGER PRIMARY KEY CHECK(id=1),last_row INTEGER NOT NULL);
    INSERT OR IGNORE INTO cursor_state VALUES(1,0);
    CREATE TABLE IF NOT EXISTS rejected(source_row INTEGER PRIMARY KEY,event_id TEXT NOT NULL,reason TEXT NOT NULL);
    """)
    for table in ("decisions","observations","rejected","observation_errors"):
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")
    db.execute("PRAGMA foreign_keys=ON")

def immutable_insert(db,table,keys,payload):
    body=canonical(payload)
    if table=="decisions":
        sql="SELECT payload FROM decisions WHERE event_id=?"; args=keys[:1]
    elif table=="observations":
        sql="SELECT payload FROM observations WHERE event_id=? AND rule_id=? AND frame=? AND side=? AND horizon=?";args=keys
    else: raise ValueError("invalid_table")
    old=db.execute(sql,args).fetchone()
    if old:
        if old[0]!=body: raise ValueError("immutable_evidence_conflict")
        return False
    db.execute("INSERT INTO "+table+" VALUES("+",".join("?" for _ in range(len(keys)+1))+")",(*keys,body))
    return True

def tick(root,*,now):
    root=Path(root); target=root/"decision-experience-v3.sqlite"
    if target.is_symlink(): raise ValueError("untrusted_target")
    out={"mode":"synthetic_experience_memory","checked_at":now,"markets":{},"ingested":0,"new_observations":0,
         "execution_authorized":False,"actual_model_decisions":0,"verified_broker_settlements":0,"orders_submitted":0,"paid_ai_requests":0,
         "warning":"Signal observations following WAIT are counterfactual price paths, not decision returns or broker settlements."}
    with closing(ro(root/"shadow-decisions-v3.sqlite")) as source,closing(ro(root/"opportunities-v3.sqlite")) as events,closing(ro(root/"market-v3.sqlite")) as market,closing(sqlite3.connect(target,timeout=5)) as db:
        initialize(db)
        with db:
            db.execute("BEGIN IMMEDIATE")
            last=db.execute("SELECT last_row FROM cursor_state WHERE id=1").fetchone()[0]
            rows=source.execute("SELECT rowid,event_id,symbol,payload FROM decisions WHERE rowid>? ORDER BY rowid LIMIT 101",(last,)).fetchall()
            out["ingest_backlog"]=len(rows)>100
            for rid,eid,s,raw in rows[:100]:
                try:
                    row=events.execute("SELECT payload FROM events WHERE event_id=? AND symbol=?",(eid,s)).fetchone()
                    if not row: raise ValueError("missing_event")
                    record=project(json.loads(row[0]),json.loads(raw),s,eid,now=now)
                    if immutable_insert(db,"decisions",(eid,s),record): out["ingested"]+=1
                    observed=record["opportunity"]["context"].get("context_observed_at")
                    if type(observed) is int and record["opportunity"]["as_of"]<=observed<=now:
                        db.execute("INSERT OR IGNORE INTO pending VALUES(?,?)",(eid,(observed//300+1)*300+900))
                except (ValueError,TypeError,KeyError,AttributeError) as e:
                    db.execute("INSERT OR IGNORE INTO rejected VALUES(?,?,?)",(rid,eid,type(e).__name__))
                db.execute("UPDATE cursor_state SET last_row=? WHERE id=1",(rid,))
            def bars(s,a,b):
                return [json.loads(x[0]) for x in market.execute("SELECT payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<? ORDER BY stamp",(s,a,b))]
            due=db.execute("SELECT p.event_id,d.payload FROM pending p JOIN decisions d USING(event_id) WHERE p.due<=? ORDER BY p.due,p.event_id LIMIT 101",(now,)).fetchall()
            out["observation_backlog"]=len(due)>100
            for eid,raw in due[:100]:
                record=json.loads(raw)
                try: observations=evaluate_event(record["opportunity"],bars,now=now)
                except (ValueError,KeyError,TypeError,AttributeError) as e:
                    db.execute("INSERT OR IGNORE INTO observation_errors VALUES(?,?)",(eid,type(e).__name__))
                    db.execute("DELETE FROM pending WHERE event_id=?",(eid,)); continue
                unfinished=[]
                for r in observations:
                    k=(eid,r["rule_id"],r["frame"],r["direction"],r["horizon_minutes"])
                    if db.execute("SELECT 1 FROM observations WHERE event_id=? AND rule_id=? AND frame=? AND side=? AND horizon=?",k).fetchone(): continue
                    if r["status"]=="pending": unfinished.append(r["reference_end"]); continue
                    if r["status"]=="missing_candles":
                        # Allow late collection for 24h; preserve missing as explicit terminal evidence thereafter.
                        if now<r["reference_end"]+86400:
                            unfinished.append(now+300); continue
                    item={"mode":"counterfactual_signal_path","decision_action":"WAIT","observation":r,"actual_trade_outcome":False,"execution_authorized":False}
                    if immutable_insert(db,"observations",k,item): out["new_observations"]+=1
                if unfinished: db.execute("UPDATE pending SET due=? WHERE event_id=?",(min(unfinished),eid))
                else: db.execute("DELETE FROM pending WHERE event_id=?",(eid,))

        for s in ROUTE:
            n=db.execute("SELECT count(*) FROM decisions WHERE symbol=?",(s,)).fetchone()[0]
            records=[json.loads(r[0]) for r in db.execute("SELECT payload FROM decisions WHERE symbol=? ORDER BY rowid DESC LIMIT 500",(s,))]
            obs=db.execute("SELECT count(*) FROM observations o JOIN decisions d USING(event_id) WHERE d.symbol=?",(s,)).fetchone()[0]
            pending=db.execute("SELECT count(*) FROM pending p JOIN decisions d USING(event_id) WHERE d.symbol=?",(s,)).fetchone()[0]
            out["markets"][s]={"decisions":n,"recent_exact_requests":sum(r["request_provenance"]=="captured_at_dispatch" for r in records),
                "recent_reconstructed_requests":sum(r["request_provenance"]=="reconstructed_payload_verified" for r in records),
                "recent_request_counts_truncated":n>500,"counterfactual_observations":obs,"pending_events":pending,
                "actual_model_decisions":0,"verified_broker_settlements":0}
        out["observation_errors"]=db.execute("SELECT count(*) FROM observation_errors").fetchone()[0]
        out["rejected_receipts"]=db.execute("SELECT count(*) FROM rejected").fetchone()[0]
    atomic_json(root/"decision-experience-status-v3.json",out)
    return out
