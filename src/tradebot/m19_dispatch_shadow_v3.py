"""Dual-interface dispatch rehearsal. No completion transport or order authority."""
import json,sqlite3,time
from pathlib import Path
from contextlib import closing
from tradebot.model_wire_v3 import MODEL_IDS,build_request,parse_fixture
from tradebot.messages_wire_v3 import URL,normalize
from tradebot.opportunity_journal_v3 import ROUTE,canonical,digest
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.product_context_v3 import collect_specs
from tradebot.research_collector_v3 import atomic_json

def prepare_preview(event,spec,*,now):
    s=event["symbol"]
    if event["model_if_enabled"]!=ROUTE[s] or event.get("signal_rule")!="one_of_n" or not event["new_signals"]:
        raise ValueError("not_current_route_candidate")
    if event.get("ai_dispatched") is not False or event.get("orders_submitted")!=0:
        raise ValueError("not_shadow")
    w=build_request(event,spec,now=now)
    q=w["request"]
    a=wait_fixture(q)
    if s=="BTCUSD":
        endpoint=URL
        body={"model":MODEL_IDS[s],"max_tokens":1024,"system":q["system"],
              "messages":[{"role":"user","content":canonical(q["payload"])}]}
        envelope={"model":MODEL_IDS[s],"type":"message","role":"assistant","stop_reason":"end_turn",
                  "content":[{"type":"text","text":canonical(a)}]}
        response=parse_fixture(normalize(envelope),w)
        interface="messages"
    else:
        endpoint=w["endpoint"];body=w["body"];interface="chat_completions"
        response=parse_fixture({"model":MODEL_IDS[s],"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":canonical(a)}}]},w)
    return {"event_id":event["event_id"],"symbol":s,"model":MODEL_IDS[s],"interface":interface,
            "wire_sha256":digest({"endpoint":endpoint,"body":body}),"signal_count":len(event["new_signals"]),
            "source":"local_wait_fixture","action":response["action"],"execution_authorized":False,
            "paid_ai_requests":0,"orders_submitted":0}

def tick(root,*,spec_reader=collect_specs,clock=time.time):
    root=Path(root); specs=spec_reader();now=int(clock())
    report={"mode":"dual_interface_dispatch_shadow","checked_at":now,"markets":{},
            "execution_authorized":False,"paid_ai_requests":0,"orders_submitted":0}
    source=root/"opportunities-v3.sqlite";target=root/"m19-dispatch-shadow-v3.sqlite"
    if source.is_symlink() or target.is_symlink():raise ValueError("untrusted_database")
    with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True)) as src,closing(sqlite3.connect(target,timeout=10)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS previews(event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,body TEXT NOT NULL)")
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op.lower()} BEFORE {op} ON previews BEGIN SELECT RAISE(ABORT,'immutable preview');END")
        for s in ROUTE:
            item={"model":MODEL_IDS[s],"interface":"messages" if s=="BTCUSD" else "chat_completions","fresh":0,"rehearsed":0,"duplicates":0,"failed":0,"legacy_route":0}
            rows=src.execute("SELECT event_id,payload FROM events WHERE symbol=? AND as_of BETWEEN ? AND ? ORDER BY as_of,event_id LIMIT 101",(s,now-150,now)).fetchall()
            item["truncated"]=len(rows)>100
            for key,raw in rows[:100]:
                item["fresh"]+=1
                try:
                    e=json.loads(raw)
                    if (e["event_id"],e["symbol"])!=(key,s):raise ValueError("identity")
                    if e["model_if_enabled"]!=ROUTE[s]:
                        item["legacy_route"]+=1;continue
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        if db.execute("SELECT 1 FROM previews WHERE event_id=?",(key,)).fetchone():
                            item["duplicates"]+=1;continue
                        if specs[s]["status"]!="ready":raise ValueError("product_unavailable")
                        p=prepare_preview(e,specs[s]["data"],now=now)
                        db.execute("INSERT INTO previews VALUES(?,?,?)",(key,s,canonical(p)))
                        item["rehearsed"]+=1
                except (ValueError,KeyError,TypeError,sqlite3.Error):item["failed"]+=1
            report["markets"][s]=item
    atomic_json(root/"m19-dispatch-shadow-v3.json",report)
    return report
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--directory",required=True)
    print(json.dumps(tick(p.parse_args().directory)))
