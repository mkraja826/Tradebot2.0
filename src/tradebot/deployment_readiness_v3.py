"""Deployment handoff diagnostics only; never grants execution authority."""
from pathlib import Path
from datetime import datetime,timezone
from time import time
from urllib.request import build_opener,ProxyHandler
import json
from tradebot.dashboard_context_v3 import NoRedirect,read_accounts
from tradebot.commissioning_v3 import audit
from tradebot.research_collector_v3 import atomic_json
from tradebot.model_wire_v3 import MODEL_IDS

def checkpoint():
    with build_opener(ProxyHandler({}),NoRedirect()).open("http://127.0.0.1:8765/api/risk/checkpoints",timeout=5) as response:
        raw=response.read(200001)
    if len(raw)>200000: raise ValueError("oversized_checkpoint")
    return json.loads(raw)

def checkpoint_status(raw,now):
    unknown={"status":"unavailable","blocking_conditions":[],"prerequisites_met":None}
    try:
        at=datetime.fromisoformat(raw["as_of"])
        if raw["mode"]!="read_only" or at.tzinfo is None or not 0<=now-at.timestamp()<=90:
            return unknown
        conditions=raw["blocking_conditions"]
        if not isinstance(conditions,list) or any(not isinstance(x,str) for x in conditions): return unknown
        return {"status":raw["status"],"blocking_conditions":conditions,
                "prerequisites_met":raw["checkpoint_prerequisites_met"] is True,
                "source":"existing_checkpoint_diagnostic_not_account_specific",
                "execution_authorized":False}
    except (KeyError,ValueError,TypeError,AttributeError): return unknown

def finalize(root,*,reader=read_accounts,checkpoint_reader=checkpoint,clock=time):
    root=Path(root)
    try: accounts=reader()
    except Exception: accounts={}
    try: risk=checkpoint_reader()
    except Exception: risk={}
    instant=clock(); now=int(instant)
    a=audit(root,now=now)
    result={"mode":"shadow_deployment_only","checked_at":now,"research_checks_passed":a["research_checks_passed"],
            "checkpoint":checkpoint_status(risk,instant),"markets":{},"execution_authorized":False,
            "live_ai_enabled":False,"orders_submitted":0,"paid_ai_requests":0}
    for s,m in MODEL_IDS.items():
        account=accounts.get(s,{})
        result["markets"][s]={"model_id":m,"identity_observed":account.get("signed_account_verified") is True,
            "halted":account.get("halted"),"account_context":account.get("status","unavailable"),
            "missing_interfaces":["authorized_full_signed_account_context","authenticated_model_provider",
              "commissioned_broker_execution_adapter"],
            "status":"shadow_only"}
    try:
        d=json.loads((root/"shadow-dispatch-status-v3.json").read_text())
        result["shadow_worker_fresh"]=d["mode"]=="automatic_shadow_dispatch" and 0<=now-d["checked_at"]<=150 and d["execution_authorized"] is False
    except (ValueError,TypeError,KeyError,OSError): result["shadow_worker_fresh"]=False
    atomic_json(root/"deployment-readiness-v3.json",result)
    return result
