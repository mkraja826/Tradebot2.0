"""M15.4 local decision-validation harness. No completion or order transport."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from decimal import Decimal
from contextlib import closing
import json,sqlite3
from tradebot.model_wire_v3 import MODEL_IDS,build_request,build_synthetic_fixture,parse_fixture
from tradebot.opportunity_journal_v3 import OpportunityJournal,canonical
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.execution_preview_v3 import translate
from tradebot.decision_quality_v3 import assess
from tradebot.dashboard_context_v3 import read_accounts
from tradebot.product_context_v3 import collect_specs
from tradebot.research_collector_v3 import atomic_json

def envelope(w,r):
    return {"model":w["body"]["model"],"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":canonical(r)}}]}

def exercise(s,spec,now):
    signal={"id":"B01" if s=="BTCUSD" else "G01","frame":"5m","direction":"LONG","closed_at":now//300*300}
    context={"symbol":s,"as_of":now,"context_observed_at":now,"mode":"shadow","fixture_only":True,
        "market":{"frames":{"5m":{"status":"ready","closed_at":signal["closed_at"],"features":{"rsi14":55}}}},
        "strategy_learning":{"status":"unavailable","reason":"synthetic_fixture","strategy_eligibility_changed":False}}
    with TemporaryDirectory() as d:
        e=OpportunityJournal(Path(d)/"fixture.sqlite").record(
            dict(symbol=s,as_of=now,signals=[signal],ai_dispatched=False,orders_submitted=0),context)
    account={"symbol":s,"mode":"synthetic_fixture","net_equity_usd":"100","available_margin_usd":"80","positions":[],"open_order_count":0}
    w=build_synthetic_fixture(e,spec,account,now=now)
    q=w["request"]; tick=Decimal(spec["tick_size"]); price=tick*1000; unit=Decimal(spec["contract_value"])
    passed=[]
    for action in ("WAIT","LONG","SHORT"):
        r=wait_fixture(q)
        if action!="WAIT":
            sign=1 if action=="LONG" else -1
            r.update(action=action,rationale="Synthetic contract test only",plan=dict(entry_type="MARKET",
                entry_reference=float(price),contracts=1,leverage=1,margin_quote=float(price*unit),
                stop_loss=float(price-sign*10*tick),take_profit=float(price+sign*20*tick),
                holding_minutes=15,management="Synthetic test only"))
        a=parse_fixture(envelope(w,r),w)
        preview=translate(q,a,spec,now=now)
        diagnostic=assess(q,a,spec,decision_at=now)
        if preview["execution_authorized"] or diagnostic["execution_authorized"]: raise ValueError("unexpected_authority")
        passed.append(action)
    return {"status":"passed","source":"synthetic_fixture","actions":passed,"actual_model_verified":False}

def tick(root,*,spec_reader=collect_specs,account_reader=read_accounts,clock=time):
    root=Path(root); specs=spec_reader(); accounts=account_reader(); now=int(clock())
    out={"mode":"offline_decision_validation","checked_at":now,"markets":{},"execution_authorized":False,"paid_ai_requests":0,"orders_submitted":0}
    with closing(sqlite3.connect((root/"opportunities-v3.sqlite").resolve().as_uri()+"?mode=ro",uri=True)) as db:
        for s in MODEL_IDS:
            item={"fixture":{"status":"product_unavailable"},"actual_opportunity_preview":"unavailable","authenticated_model_verified":False}
            p=specs.get(s,{})
            if p.get("status")=="ready":
                item["fixture"]=exercise(s,p["data"],now)
                row=db.execute("SELECT payload FROM events WHERE symbol=? ORDER BY as_of DESC,event_id DESC LIMIT 1",(s,)).fetchone()
                if row:
                    e=json.loads(row[0])
                    if not 0<=now-e["as_of"]<=150: item["actual_opportunity_preview"]="expired"
                    else:
                        w=build_request(e,p["data"],now=now,account_context=accounts[s])
                        r=wait_fixture(w["request"]);parse_fixture(envelope(w,r),w)
                        item["actual_opportunity_preview"]="offline_wait_passed"
            out["markets"][s]=item
    atomic_json(root/"m15-decision-validation-v3.json",out)
    return out

