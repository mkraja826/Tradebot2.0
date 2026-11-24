from tradebot.strategy_registry_v3 import valid_signal_rule
"""M11 read-only commissioning checks. Never authorizes live execution."""
from pathlib import Path
from contextlib import closing
import sqlite3,json,time
from tradebot.opportunity_journal_v3 import digest,ROUTE,known_route
from tradebot.market_data_v3 import FRAMES
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.dashboard_snapshot_v3 import snapshot
from tradebot.research_collector_v3 import atomic_json

DATABASES=("market-v3.sqlite","opportunities-v3.sqlite","positions-v3.sqlite","ai-replay-v3.sqlite","dispatch-preview-v3.sqlite")
def ro(path):
    if path.is_symlink() or not path.is_file(): raise ValueError("missing_or_untrusted_database")
    return sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=10)

def verify_events(db):
    db.execute("BEGIN")
    if db.execute("PRAGMA foreign_key_check").fetchone(): raise ValueError("orphan_signal")
    events=0; signals=0; replays=0
    for eid,s,stamp,raw in db.execute("SELECT event_id,symbol,as_of,payload FROM events"):
        e=json.loads(raw)
        if (e["symbol"],e["event_id"],e["as_of"])!=(s,eid,stamp) or not known_route(s,e["model_if_enabled"]):
            raise ValueError("event_identity_mismatch")
        if e["mode"]!="shadow" or e["execution_authorized"] is not False or e["ai_dispatched"] is not False or e["orders_submitted"]!=0:
            raise ValueError("not_shadow")
        if digest(e["context"])!=e["context_sha256"]: raise ValueError("context_hash_mismatch")
        keys=sorted((s,x["id"],x["frame"],x["direction"],x["closed_at"]) for x in e["new_signals"])
        prefix="B" if s=="BTCUSD" else "G"
        if not keys or len(set(keys))!=len(keys) or digest(keys)!=eid: raise ValueError("signal_identity_mismatch")
        for _,r,f,d,t in keys:
            if not valid_signal_rule(s,r,f) or d not in ("LONG","SHORT") or t!=stamp//FRAMES[f]*FRAMES[f]:
                raise ValueError("signal_scope_mismatch")
        seen=db.execute("SELECT symbol,rule_id,frame,direction,closed_at FROM seen WHERE event_id=? ORDER BY symbol,rule_id,frame,direction,closed_at",(eid,)).fetchall()
        if seen!=keys: raise ValueError("journal_index_mismatch")
        q=prepare(e); reply=validate(wait_fixture(q),q)
        if reply["action"]!="WAIT": raise ValueError("fixture_mismatch")
        events+=1; signals+=len(keys); replays+=1
    return {"events":events,"signals":signals,"synthetic_wait_replays":replays}

def audit(root,*,now=None):
    root=Path(root); now=int(time.time()) if now is None else now
    checks={}
    for name in DATABASES:
        try:
            with closing(ro(root/name)) as db:
                checks[name]="ok" if db.execute("PRAGMA quick_check").fetchall()==[("ok",)] else "failed"
        except (ValueError,sqlite3.Error): checks[name]="unavailable"
    try:
        with closing(ro(root/"opportunities-v3.sqlite")) as db: events=verify_events(db)
        events["status"]="passed"
    except (ValueError,KeyError,TypeError,sqlite3.Error) as e: events={"status":"failed","error_type":type(e).__name__}
    d=snapshot(root,now=now)
    research_ready=all(x=="ok" for x in checks.values()) and events["status"]=="passed" and all(d["sources"][x]["state"]=="fresh" for x in ("collector","scanner","position","learning"))
    result={"mode":"research_commissioning","checked_at":now,"databases":checks,"journal_audit":events,"sources":d["sources"],
        "research_checks_passed":research_ready,"live_ai_verified":False,"execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0}
    atomic_json(root/"commissioning-v3.json",result)
    return result
