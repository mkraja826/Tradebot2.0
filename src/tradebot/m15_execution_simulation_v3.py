"""Commissioning simulation using current public specs and synthetic receipts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from decimal import Decimal
from contextlib import closing
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.model_wire_v3 import MODEL_IDS,build_synthetic_fixture,parse_fixture
from tradebot.m15_decision_validation_v3 import envelope
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.execution_preview_v3 import translate
from tradebot.synthetic_lifecycle_v3 import LifecycleLedger,fixture_receipt,fixture_protections
from tradebot.product_context_v3 import collect_specs
from tradebot.research_collector_v3 import atomic_json

def exercise(symbol,spec,*,now,side):
    with TemporaryDirectory() as d:
        root=Path(d); sig=dict(id="B01" if symbol=="BTCUSD" else "G01",frame="5m",direction=side,closed_at=now//300*300)
        e=OpportunityJournal(root/"fixture-events.sqlite").record(dict(symbol=symbol,as_of=now,signals=[sig],ai_dispatched=False,orders_submitted=0),dict(symbol=symbol,as_of=now,fixture_only=True))
        w=build_synthetic_fixture(e,spec,dict(symbol=symbol,mode="synthetic_fixture"),now=now)
        q=w["request"]; r=wait_fixture(q); tick=Decimal(spec["tick_size"]); price=tick*1000; sign=1 if side=="LONG" else -1
        r.update(action=side,rationale="Synthetic lifecycle fixture",plan=dict(entry_type="MARKET",entry_reference=float(price),
            contracts=3,leverage=1,margin_quote=float(3*price*Decimal(spec["contract_value"])),
            stop_loss=float(price-sign*10*tick),take_profit=float(price+sign*20*tick),holding_minutes=15,management="Synthetic only"))
        a=parse_fixture(envelope(w,r),w); p=translate(q,a,spec,now=now)
        ledger=LifecycleLedger(root/"fixture-lifecycle.sqlite")
        assert ledger.reserve(p)=="reserved"
        assert ledger.reserve(p)=="already_reserved"
        x=ledger.observe(p,fixture_receipt(p,0,"open"),[],stamp=now)
        assert x["entry_state"]=="fixture_pending"
        x=ledger.observe(p,fixture_receipt(p,1,"open"),[],stamp=now+1)
        assert x["protection_state"]=="fixture_protection_unverified"
        x=ledger.observe(p,fixture_receipt(p,1,"open"),fixture_protections(p,1),stamp=now+2)
        assert x["protection_state"]=="fixture_bracket_matched"
        x=ledger.observe(p,None,[],stamp=now+3)
        assert x["entry_state"]=="unknown_requires_reconciliation"
        ledger=LifecycleLedger(root/"fixture-lifecycle.sqlite")
        assert ledger.reserve(p)=="already_reserved"
        x=ledger.observe(p,fixture_receipt(p,3,"closed"),fixture_protections(p,1),stamp=now+4)
        assert x["protection_state"]=="fixture_protection_unverified"
        x=ledger.observe(p,fixture_receipt(p,3,"closed"),fixture_protections(p,3),stamp=now+5)
        assert x["protection_state"]=="fixture_bracket_matched"
        assert ledger.observe(p,fixture_receipt(p,3,"closed"),fixture_protections(p,3),stamp=now+5)=="duplicate"
        with closing(ledger.connect()) as db:
            assert db.execute("PRAGMA quick_check").fetchone()==("ok",)
            assert not db.execute("PRAGMA foreign_key_check").fetchone()
        return {"status":"passed","side":side,"observations":6,"duplicate_prevented":True,"restart_reconciled_fixture":True,"broker_verified":False}

def tick(root,*,spec_reader=collect_specs,clock=time):
    specs=spec_reader(); now=int(clock())
    out={"mode":"offline_execution_commissioning","checked_at":now,"markets":{},"execution_authorized":False,
         "orders_submitted":0,"paid_ai_requests":0,"actual_broker_verified":False,"scanner_control":False}
    for s in MODEL_IDS:
        item=specs.get(s,{})
        out["markets"][s]={"product_status":item.get("status","unavailable"),"fixtures":[]}
        if item.get("status")=="ready":
            out["markets"][s]["fixtures"]=[exercise(s,item["data"],now=now,side=side) for side in ("LONG","SHORT")]
    atomic_json(Path(root)/"m15-execution-simulation-v3.json",out)
    return out
