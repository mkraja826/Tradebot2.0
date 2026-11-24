"""Bounded paper-only decision dispatch core. Caller must supply an authorized transport.
No credentials, autonomous service, broker calls or execution authority in this module.
"""
import sqlite3,time
from pathlib import Path
from contextlib import closing
from tradebot.model_wire_v3 import build_synthetic_fixture,build_text_fixture,parse_fixture
from tradebot.messages_wire_v3 import build,parse,URL
from tradebot.opportunity_journal_v3 import ROUTE,canonical,digest
from tradebot.provider_diagnostics_v3 import classify

def prepare(event,spec,*,now):
    s=event["symbol"]
    if event["model_if_enabled"]!=ROUTE[s] or event.get("signal_rule")!="one_of_n" or not event["new_signals"]:
        raise ValueError("invalid_current_candidate")
    if event.get("ai_dispatched") is not False or event.get("orders_submitted")!=0:
        raise ValueError("shadow_only")
    account={"symbol":s,"mode":"synthetic_fixture","net_equity_usd":"100",
             "available_margin_usd":"80","positions":[],"open_order_count":0}
    w=(build_text_fixture if s=="BTCUSD" else build_synthetic_fixture)(event,spec,account,now=now)
    q=w["request"]
    q["system"]+="\nPaper research only. All account amounts and positions are hypothetical, not actual broker state. Do not execute any proposal."
    w["body"]["messages"][0]["content"]=q["system"]
    return w

class Campaign:
    def __init__(self,path,*,request_limit):
        if type(request_limit) is not int or not 1<=request_limit<=100:
            raise ValueError("invalid_request_limit")
        self.path=Path(path)
        if self.path.is_symlink():raise ValueError("untrusted_journal")
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS budget(id INTEGER PRIMARY KEY CHECK(id=1),request_limit INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO budget VALUES(1,?)",(request_limit,))
            if db.execute("SELECT request_limit FROM budget WHERE id=1").fetchone()!=(request_limit,):
                raise ValueError("budget_change_refused")
            db.execute("CREATE TABLE IF NOT EXISTS requests(event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,reserved_at INTEGER NOT NULL,request_hash TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT)")
            db.execute("CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON requests BEGIN SELECT RAISE(ABORT,'immutable reservation');END")
            db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_receipt BEFORE UPDATE ON requests
             WHEN OLD.state!='reserved_outcome_unknown' OR NEW.event_id!=OLD.event_id OR NEW.symbol!=OLD.symbol
             OR NEW.reserved_at!=OLD.reserved_at OR NEW.request_hash!=OLD.request_hash
             OR NEW.state NOT IN ('validated_paper_proposal','response_rejected','transport_outcome_unknown')
             OR NEW.receipt IS NULL BEGIN SELECT RAISE(ABORT,'immutable reservation');END""")
            db.execute("CREATE TRIGGER IF NOT EXISTS no_budget_change BEFORE UPDATE ON budget BEGIN SELECT RAISE(ABORT,'immutable budget');END")
            db.execute("CREATE TRIGGER IF NOT EXISTS no_budget_delete BEFORE DELETE ON budget BEGIN SELECT RAISE(ABORT,'immutable budget');END")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db
    def reserve(self,key,s,stamp,h):
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM requests WHERE event_id=?",(key,)).fetchone():return "duplicate"
            n=db.execute("SELECT count(*) FROM requests").fetchone()[0]
            limit=db.execute("SELECT request_limit FROM budget WHERE id=1").fetchone()[0]
            if n>=limit:return "budget_exhausted"
            db.execute("INSERT INTO requests VALUES(?,?,?,?,?,NULL)",(key,s,stamp,h,"reserved_outcome_unknown"))
            return "reserved"
    def finish(self,key,state,receipt):
        if state not in ("validated_paper_proposal","response_rejected","transport_outcome_unknown"):
            raise ValueError("invalid_state")
        with closing(self.connect()) as db,db:
            if db.execute("UPDATE requests SET state=?,receipt=? WHERE event_id=? AND state='reserved_outcome_unknown'",(state,canonical(receipt),key)).rowcount!=1:
                raise ValueError("reservation_not_pending")
    def counts(self):
        with closing(self.connect()) as db:
            limit=db.execute("SELECT request_limit FROM budget WHERE id=1").fetchone()[0]
            states=dict(db.execute("SELECT state,count(*) FROM requests GROUP BY state"))
        return {"limit":limit,"reserved":sum(states.values()),"remaining":limit-sum(states.values()),"states":states}

def dispatch(campaign,event,spec,*,transport,clock=time.time):
    now=int(clock());w=prepare(event,spec,now=now)
    s=event["symbol"];key=event["event_id"]
    endpoint=URL if s=="BTCUSD" else w["endpoint"]
    body=build(w) if s=="BTCUSD" else w["body"]
    headers={"anthropic-version":"2023-06-01"} if s=="BTCUSD" else {}
    h=digest({"endpoint":endpoint,"body":body,"headers":headers})
    if len(canonical(body).encode())>256000:raise ValueError("oversized_request")
    now=int(clock())
    if not 0<=now-event["as_of"]<=150:raise ValueError("stale_opportunity")
    reservation=campaign.reserve(key,s,now,h)
    receipt={"event_id":key,"symbol":s,"model":body["model"],"request_sha256":h,
             "interface":"messages" if s=="BTCUSD" else "chat_completions",
             "account_basis":"hypothetical","execution_authorized":False,"orders_submitted":0}
    if reservation!="reserved":return dict(receipt,status=reservation)
    start=time.monotonic()
    try:
        response=transport(endpoint,body,headers,20)
    except Exception as exc:
        receipt.update(status="transport_outcome_unknown",failure_code=classify(exc,"transport"))
    else:
        try:
            result=parse(response,w,body) if s=="BTCUSD" else parse_fixture(response,w)
            if not 0<=int(clock())-event["as_of"]<=150:raise ValueError("stale_response")
            receipt.update(status="validated_paper_proposal",response_sha256=digest(response),decision=result)
        except Exception as exc:
            receipt.update(status="response_rejected",failure_code=classify(exc,"validation"))
    receipt.update(elapsed_ms=round((time.monotonic()-start)*1000),checked_at=int(clock()))
    campaign.finish(key,receipt["status"],receipt)
    return receipt
