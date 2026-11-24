"""M12 automatic shadow dispatch; no network, credentials or order authority."""
from contextlib import closing
from pathlib import Path
from time import time
import json,sqlite3
from tradebot.dispatch_journal_v3 import DispatchJournal
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.opportunity_journal_v3 import canonical,digest,ROUTE
from tradebot.research_collector_v3 import atomic_json

def tick(root,*,now=None):
    root=Path(root); now=int(time()) if now is None else now
    journal=DispatchJournal(root/"dispatch-preview-v3.sqlite")
    recovery=journal.recover(now=now)
    result={"mode":"automatic_shadow_dispatch","checked_at":now,"recovery":recovery,
            "markets":{},"paid_ai_requests":0,"orders_submitted":0,"execution_authorized":False}
    uri=(root/"opportunities-v3.sqlite").resolve().as_uri()+"?mode=ro"
    with closing(sqlite3.connect(uri,uri=True,timeout=10)) as db:
        for s in ROUTE:
            item={"fresh_candidates":0,"synthetic_completed":0,"duplicate_or_terminal":0,"failed":0}
            rows=db.execute("SELECT payload FROM events WHERE symbol=? AND as_of BETWEEN ? AND ? ORDER BY as_of,event_id LIMIT 101",(s,now-150,now)).fetchall()
            item["truncated"]=len(rows)>100
            for (raw,) in rows[:100]:
                item["fresh_candidates"]+=1
                try:
                    e=json.loads(raw); key=e["event_id"]
                    if e["symbol"]!=s or e.get("ai_dispatched") is not False or e.get("orders_submitted")!=0:
                        raise ValueError("invalid_shadow_event")
                    journal.stage(e,now=now)
                    if not journal.claim_preview(key,now=now):
                        item["duplicate_or_terminal"]+=1; continue
                    try:
                        q=prepare(e); a=validate(wait_fixture(q),q)
                        if a["action"]!="WAIT": raise ValueError("unexpected_fixture_action")
                        store_fixture(root/"shadow-decisions-v3.sqlite",e,q,a,now=now)
                    except Exception:
                        journal.finish_preview(key,"preview_failed",now=now)
                        raise
                    if journal.finish_preview(key,"synthetic_completed",now=now):
                        item["synthetic_completed"]+=1
                    else: item["failed"]+=1
                except (ValueError,KeyError,TypeError,sqlite3.Error):
                    item["failed"]+=1
            result["markets"][s]=item
    result["journal_counts"]=journal.counts()
    atomic_json(root/"shadow-dispatch-status-v3.json",result)
    return result

def store_fixture(path,e,q,a,*,now=None):
    receipt={"mode":"synthetic_wait_only","request_sha256":q["request_sha256"],
             "response":a,"response_sha256":digest(a),"execution_authorized":False}
    if now is not None:
        if type(now) is not int or not 0<=now-e["as_of"]<=150: raise ValueError("invalid_fixture_time")
        receipt.update(request=q,full_request_sha256=digest(q),recorded_at=now)
    body=canonical(receipt)
    with closing(sqlite3.connect(path,timeout=10)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS decisions(event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,payload TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        old=db.execute("SELECT payload FROM decisions WHERE event_id=?",(e["event_id"],)).fetchone()
        if old and old[0]!=body: raise ValueError("conflicting_fixture")
        db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?)",(e["event_id"],e["symbol"],body))

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--directory",type=Path,required=True)
    r=tick(p.parse_args().directory)
    print(json.dumps({"markets":r["markets"],"journal_counts":r["journal_counts"]}))
