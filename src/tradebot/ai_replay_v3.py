"""Offline replay journal. Synthetic replies cannot become execution receipts."""
import json,sqlite3
from contextlib import closing
from pathlib import Path
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.opportunity_journal_v3 import canonical,digest

def replay(source,destination,fixture):
    uri=Path(source).resolve().as_uri()+"?mode=ro"
    with closing(sqlite3.connect(uri,uri=True)) as db:
        events=[json.loads(r[0]) for r in db.execute("SELECT payload FROM events ORDER BY as_of,event_id").fetchall()]
    counts={"new":0,"duplicate":0,"rejected":0,"actions":{}}
    with closing(sqlite3.connect(destination)) as db,db:
        db.execute("""CREATE TABLE IF NOT EXISTS replays(
          event_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, request_hash TEXT NOT NULL,
          payload TEXT NOT NULL)""")
        db.execute("BEGIN IMMEDIATE")
        for event in events:
            if db.execute("SELECT 1 FROM replays WHERE event_id=?",(event["event_id"],)).fetchone():
                counts["duplicate"]+=1; continue
            req=prepare(event)
            try: reply=validate(fixture(req),req)
            except (ValueError,TypeError,KeyError):
                counts["rejected"]+=1; continue
            record={"mode":"synthetic_replay","request":req,"response":reply,
                    "response_sha256":digest(reply),"execution_authorized":False,
                    "paid_ai_requests":0,"orders_submitted":0}
            db.execute("INSERT INTO replays VALUES(?,?,?,?)",(event["event_id"],event["symbol"],req["request_sha256"],canonical(record)))
            counts["new"]+=1
            a=reply["action"]; counts["actions"][a]=counts["actions"].get(a,0)+1
    return counts

def wait_fixture(req):
    p=req["payload"]
    return {**{k:p[k] for k in ("schema_version","event_id","symbol")},"action":"WAIT",
            "rationale":"Synthetic offline fixture; account context unavailable.","plan":None}
