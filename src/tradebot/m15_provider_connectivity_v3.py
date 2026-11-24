"""Model-route compatibility diagnostics, never submits a completion."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from tradebot.model_wire_v3 import MODEL_IDS,build_request,parse_fixture,check_catalogue
from tradebot.opportunity_journal_v3 import OpportunityJournal,canonical
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.product_context_v3 import collect_specs
from tradebot.research_collector_v3 import atomic_json

def compatibility(symbol,spec,*,now):
    # Fixture opportunity, not a real signal, and never persisted to the scanner.
    rule="B01" if symbol=="BTCUSD" else "G01"
    sig={"id":rule,"frame":"5m","direction":"LONG","closed_at":now//300*300}
    with TemporaryDirectory() as tmp:
        j=OpportunityJournal(Path(tmp)/"fixture.sqlite")
        event=j.record(dict(symbol=symbol,as_of=now,signals=[sig],ai_dispatched=False,orders_submitted=0),dict(symbol=symbol,as_of=now))
        wire=build_request(event,spec,now=now)
    response=wait_fixture(wire["request"])
    envelope={"model":MODEL_IDS[symbol],"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":canonical(response)}}]}
    accepted=parse_fixture(envelope,wire)==response
    return {"status":"passed" if accepted else "failed","source":"synthetic_wire_fixture",
        "request_bytes":len(canonical(wire["body"]).encode("utf-8")),"response_action":"WAIT","model_id":MODEL_IDS[symbol],
        "actual_completion_verified":False,"execution_authorized":False}

def tick(root,*,provider=None,spec_reader=collect_specs,clock=time):
    catalogue={}; status="not_provisioned"
    if provider is not None:
        try:
            catalogue=check_catalogue(provider); status="catalogue_returned"
        except Exception as e: status="unavailable:"+type(e).__name__
    try: specs=spec_reader()
    except Exception: specs={}
    now=int(clock())
    result={"mode":"provider_commissioning_read_only","checked_at":now,
        "catalogue_status":status,"catalogue_source":"caller_supplied_client" if provider is not None else None,
        "execution_authorized":False,"paid_ai_requests":0,"orders_submitted":0,"markets":{}}
    for s,m in MODEL_IDS.items():
        item={"model_id":m,"catalogue_model_listed":catalogue.get(s,{}).get("available"),
              "authentication_verified":False,"actual_completion_verified":False,
              "compatibility":{"status":"product_unavailable"},"commissioning_complete":False}
        p=specs.get(s,{})
        if p.get("status")=="ready":
            try: item["compatibility"]=compatibility(s,p["data"],now=now)
            except (ValueError,TypeError,KeyError,AttributeError) as e: item["compatibility"]={"status":"failed:"+type(e).__name__}
        result["markets"][s]=item
    atomic_json(Path(root)/"m15-provider-connectivity-v3.json",result)
    return result
