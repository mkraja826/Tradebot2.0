"""Read-only operational readiness report. Never enables trading."""
from pathlib import Path
from time import time
from tradebot.m15_commissioning_v3 import tick as commissioning_tick
from tradebot.m15_account_connectivity_v3 import tick as account_tick
from tradebot.m15_provider_connectivity_v3 import tick as provider_tick
from tradebot.m15_decision_validation_v3 import tick as decision_tick
from tradebot.m15_execution_simulation_v3 import tick as execution_tick
from tradebot.research_collector_v3 import atomic_json
from tradebot.model_wire_v3 import MODEL_IDS

MODES={"commissioning":"commissioning_diagnostic_only","account":"signed_account_commissioning_read_only",
"provider":"provider_commissioning_read_only","decision":"offline_decision_validation","execution":"offline_execution_commissioning"}

def fresh(r,name,now):
    t=r.get("checked_at")
    return (r.get("mode")==MODES[name] and type(t) is int and 0<=now-t<=150
            and r.get("execution_authorized") is False and r.get("orders_submitted")==0 and r.get("paid_ai_requests")==0)

def consolidate(reports,*,now):
    valid={k:fresh(reports.get(k,{}),k,now) for k in MODES}
    c=reports.get("commissioning",{}) if valid["commissioning"] else {}
    out={"mode":"autonomous_readiness_diagnostic_only","checked_at":now,"report_freshness":valid,
         "research_checks_passed":c.get("research_checks_passed") is True,
         "research_evidence":c.get("research_evidence",{}),"database_integrity":c.get("database_integrity",{}),
         "checkpoint":c.get("checkpoint",{}),"markets":{},"execution_authorized":False,
         "live_ai_enabled":False,"orders_submitted":0,"paid_ai_requests":0}
    for s,m in MODEL_IDS.items():
        def get(k):
            return reports[k].get("markets",{}).get(s,{}) if valid[k] else {}
        a=get("account"); p=get("provider"); d=get("decision"); e=get("execution"); b=get("commissioning")
        fixtures=e.get("fixtures",[])
        offline=(p.get("compatibility",{}).get("status")=="passed"
                 and d.get("fixture",{}).get("status")=="passed"
                 and set(d.get("fixture",{}).get("actions",[]))=={"WAIT","LONG","SHORT"}
                 and len(fixtures)==2 and {x.get("side") for x in fixtures}=={"LONG","SHORT"}
                 and all(x.get("status")=="passed" and x.get("broker_verified") is False for x in fixtures))
        out["markets"][s]={"model_id":m,"product":b.get("product","unavailable"),
            "identity_observed":a.get("dashboard",{}).get("identity_verified") is True,
            "account_context":a.get("dashboard",{}).get("status","unavailable"),
            "halted":a.get("dashboard",{}).get("halted"),
            "offline_pipeline_passed":offline,"signed_client_status":a.get("signed_client_status","unavailable"),
            "catalogue_model_listed":p.get("catalogue_model_listed"),
            "authenticated_completion_verified":False,"broker_execution_verified":False,
            "autonomous_trading_ready":False,"mode":"shadow_only",
            "remaining":["authorized_signed_account_connectivity","authenticated_provider_connectivity",
             "separately_authorized_model_validation","broker_execution_and_settlement_commissioning","existing_trading_prerequisites"]}
    return out

def tick(root):
    reports={}
    for k,fn in (("commissioning",commissioning_tick),("account",account_tick),("provider",provider_tick),
                 ("decision",decision_tick),("execution",execution_tick)):
        try: reports[k]=fn(root)
        except Exception: reports[k]={}
    out=consolidate(reports,now=int(time()))
    atomic_json(Path(root)/"m15-autonomous-readiness-v3.json",out)
    return out
