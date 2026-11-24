"""Offline compatibility with the existing FIRE validation interface."""
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from tradebot.execution_preview_v3 import translate
from tradebot.fire_probe import validate as validate_fire
from tradebot.fire_risk import assess_fire_plan
from tradebot.model_wire_v3 import build_synthetic_fixture,MODEL_IDS,request_model
from tradebot.opportunity_journal_v3 import OpportunityJournal,digest
from tradebot.ai_replay_v3 import wait_fixture
from tradebot.product_context_v3 import collect_specs
from tradebot.research_collector_v3 import atomic_json

def adapt(request,response,product,quote,budget,*,now):
    p=request["payload"];s=p["symbol"]
    if request_model(request)!=MODEL_IDS[s] or p["account"].get("mode")!="synthetic_fixture":
        raise ValueError("current_model_fixture_required")
    if p.get("product")!=product:raise ValueError("product_binding_mismatch")
    if quote.get("symbol")!=s or quote.get("mode")!="synthetic_fixture" or not 0<=now-quote["observed_at"]<=150:
        raise ValueError("fixture_quote_required")
    if budget.get("symbol")!=s or budget.get("mode")!="synthetic_fixture":
        raise ValueError("fixture_budget_required")
    if Decimal(str(budget["contract_value"]))!=Decimal(product["contract_value"]):
        raise ValueError("contract_value_mismatch")
    v=translate(request,response,product,now=now)
    out=dict(mode="offline_fire_compatibility",symbol=s,action=v["action"],preview_hash=digest(v),
             execution_authorized=False,orders_submitted=0,broker_verified=False,fire_plan=None)
    if v["action"]=="WAIT":
        out["fire_plan"]=validate_fire(dict(direction="WAIT",contracts=0,stop_loss=None,take_profit=None,leverage=None,thesis=response["rationale"]),quote,require_leverage=True)
        return dict(out,status="wait_no_order")
    e=v["entry"];pr=v["protection"]
    if e["kind"]!="MARKET":return dict(out,status="limit_execution_not_supported")
    plan=validate_fire(dict(direction=v["action"],contracts=e["contracts"],leverage=e["leverage"],
                            stop_loss=pr["stop_loss"],take_profit=pr["take_profit"]),quote,require_leverage=True)
    assess_fire_plan(plan,budget,quote)
    return dict(out,status="existing_validator_passed_fixture",fire_plan=plan,
                proposed_margin_quote=e["margin_quote"],margin_quote_broker_verified=False,
                management_execution_verified=False)

def exercise(s,spec,now):
    with TemporaryDirectory() as d:
        sig=dict(id="B01" if s=="BTCUSD" else "G01",frame="5m",direction="LONG",closed_at=now//300*300)
        e=OpportunityJournal(Path(d)/"fixture.sqlite").record(dict(symbol=s,as_of=now,signals=[sig],ai_dispatched=False,orders_submitted=0),dict(symbol=s,as_of=now,fixture_only=True))
    account=dict(symbol=s,mode="synthetic_fixture",net_equity_usd="1000",available_margin_usd="800")
    q=build_synthetic_fixture(e,spec,account,now=now)["request"]
    tick=Decimal(spec["tick_size"]);price=tick*1000;unit=Decimal(spec["contract_value"])
    quote=dict(symbol=s,mode="synthetic_fixture",observed_at=now,best_bid=str(price),best_ask=str(price))
    budget=dict(symbol=s,mode="synthetic_fixture",contract_value=str(unit),equity_usd="1000",leverage="1",max_contracts_per_entry=1,taker_commission_rate="0.0005")
    results={}
    for action,kind in (("WAIT","MARKET"),("LONG","MARKET"),("SHORT","MARKET"),("LONG","LIMIT"),("SHORT","LIMIT")):
        r=wait_fixture(q)
        if action!="WAIT":
            sign=1 if action=="LONG" else -1
            r.update(action=action,rationale="Offline fixture",plan=dict(entry_type=kind,entry_reference=float(price),contracts=1,leverage=1,margin_quote=float(price*unit),stop_loss=float(price-sign*10*tick),take_profit=float(price+sign*40*tick),holding_minutes=15,management="Fixture only"))
        a=adapt(q,r,spec,quote,budget,now=now)
        results[action+"_"+kind]=a["status"]
    return results

def tick(root):
    specs=collect_specs();now=int(time());out=dict(mode="offline_fire_compatibility_only",checked_at=now,markets={},execution_authorized=False,orders_submitted=0,paid_ai_requests=0)
    for s,a in specs.items():
        out["markets"][s]=exercise(s,a["data"],now) if a["status"]=="ready" else {"status":"product_unavailable"}
    atomic_json(Path(root)/"m23-execution-adapter-v3.json",out)
    return out
