"""M15 read-only commissioning matrix. A diagnostic is never release authority."""
from pathlib import Path
from time import time
from contextlib import closing
import json,sqlite3
from tradebot.model_wire_v3 import MODEL_IDS
from tradebot.deployment_readiness_v3 import finalize
from tradebot.connectivity_v3 import refresh
from tradebot.research_collector_v3 import atomic_json

REPORTS={
 "strategy_profiles":("strategy-profiles-v3.json","strategy_performance_advisory",660),
 "decision_quality":("decision-quality-v3.json","synthetic_decision_quality",660),
 "decision_experience":("decision-experience-status-v3.json","synthetic_experience_memory",660),
 "shadow_dispatch":("shadow-dispatch-status-v3.json","automatic_shadow_dispatch",150)}
def evidence(root,key,now):
    filename,mode,max_age=REPORTS[key]; p=Path(root)/filename
    try:
        if p.is_symlink(): raise ValueError()
        with p.open("rb") as f: raw=f.read(8_000_001)
        if len(raw)>8_000_000: raise ValueError()
        d=json.loads(raw); t=d["checked_at"]
        if d["mode"]!=mode or d["execution_authorized"] is not False or type(t) is not int or t>now: raise ValueError()
        return {"status":"fresh" if now-t<=max_age else "stale","age_seconds":now-t},d
    except (OSError,ValueError,TypeError,KeyError,AttributeError): return {"status":"unavailable"},{}
def integrity(root,name):
    p=Path(root)/name
    try:
        if p.is_symlink() or not p.is_file(): raise ValueError()
        with closing(sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            return "passed" if db.execute("PRAGMA quick_check(1)").fetchall()==[("ok",)] and not db.execute("PRAGMA foreign_key_check").fetchone() else "failed"
    except (ValueError,sqlite3.Error,OSError): return "unavailable"

def matrix(root,deployment,connectivity,*,now):
    checks={}; reports={}
    for k in REPORTS: checks[k],reports[k]=evidence(root,k,now)
    checkpoint=deployment.get("checkpoint",{})
    out={"mode":"commissioning_diagnostic_only","checked_at":now,"research_checks_passed":deployment.get("research_checks_passed") is True,
         "checkpoint":checkpoint,"research_evidence":checks,"database_integrity":{n:integrity(root,n) for n in ("shadow-decisions-v3.sqlite","decision-experience-v3.sqlite")},
         "markets":{},"execution_authorized":False,"live_ai_enabled":False,"paid_ai_requests":0,"orders_submitted":0}
    for s,model in MODEL_IDS.items():
        a=deployment.get("markets",{}).get(s,{})
        c=connectivity.get("markets",{}).get(s,{})
        out["markets"][s]={"model_id":model,"product":c.get("product","unavailable"),
             "account_identity_observed":a.get("identity_observed") is True,"account_context":a.get("account_context","unavailable"),
             "halted":a.get("halted"),"opportunity_status":c.get("opportunity_status","unavailable"),
             "wire_prepared_for_fresh_opportunity":c.get("wire_prepared") is True,
             "signed_wallet_and_margin_verified":False,"provider_authentication_verified":False,
             "authenticated_completion_verified":False,"broker_execution_verified":False,
             "broker_protection_and_settlement_verified":False,"commissioning_status":"not_ready",
             "required_owner_actions":["provision_authorized_read_only_clients_without_exposing_credentials",
                 "verify_model_catalogue_and_response_contract","resolve_existing_checkpoint_and_account_halt_via_authorized_process",
                 "separately_authorize_and_commission_demo_execution"]}
    return out

def tick(root):
    d=finalize(root); c=refresh(root); now=int(time())
    out=matrix(root,d,c,now=now)
    atomic_json(Path(root)/"m15-commissioning-v3.json",out)
    return out

