"""Provider wire adapter. Catalogue GET supported; completion is offline-only here."""
import json
from tradebot.ai import TOPBILLING_MODELS_URL,TOPBILLING_CHAT_URL
from tradebot.ai_decision_v3 import prepare,validate
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.product_context_v3 import account_unavailable

MODEL_IDS={"BTCUSD":"tb-gpt-6-1-sol","XAUTUSD":"tb-deepseek-v4-1-flash"}
def request_model(req):
    if req["payload"]["symbol"]=="BTCUSD" and req["model_if_enabled"]=="GPT-6":
        return "tb-gpt-6"
    return MODEL_IDS[req["payload"]["symbol"]]

def catalogue_status(catalogue):
    if not isinstance(catalogue,dict) or not isinstance(catalogue.get("data"),list):
        raise ValueError("invalid_model_catalogue")
    entries=catalogue["data"]
    if len(entries)>10000 or any(not isinstance(x,dict) or not isinstance(x.get("id"),str) or not x["id"].strip() for x in entries):
        raise ValueError("invalid_model_entries")
    ids={x["id"] for x in entries}
    if len(ids)!=len(entries): raise ValueError("duplicate_model_id")
    return {s:{"model_id":m,"available":m in ids} for s,m in MODEL_IDS.items()}

def check_catalogue(client):
    return catalogue_status(client._call(TOPBILLING_MODELS_URL,timeout=15))

def build_request(event,spec,*,now,account_context=None):
    s=event["symbol"]; req=prepare(event)
    if type(now) is not int or not 0<=now-event["as_of"]<=150:
        raise ValueError("stale_opportunity")
    if spec.get("symbol")!=s or spec.get("source")!="delta_demo_public_product":
        raise ValueError("wrong_product_context")
    if not 0<=now-spec["observed_at"]<=300:
        raise ValueError("stale_product_context")
    req["payload"]["product"]=spec
    account=account_unavailable(s) if account_context is None else account_context
    if account.get("symbol")!=s or account.get("subaccount")!=("BTC" if s=="BTCUSD" else "GOLD") or account.get("status") not in ("partial","unavailable"):
        raise ValueError("invalid_read_only_account_context")
    req["payload"]["account"]=account
    req["request_sha256"]=digest(req["payload"])
    return _wire(req,"offline_wire_preview")

def _wire(req,mode):
    s=req["payload"]["symbol"]
    body={"model":request_model(req),"messages":[{"role":"system","content":req["system"]},
          {"role":"user","content":canonical(req["payload"])}],"response_format":{"type":"json_object"}}
    return {"request":req,"body":body,"endpoint":TOPBILLING_CHAT_URL,
            "mode":mode,"execution_authorized":False}

def build_synthetic_fixture(event,spec,account,*,now):
    # Directional testing is explicitly distinct from the read-only wire.
    base=build_request(event,spec,now=now)
    req=prepare(event,account)
    if req["payload"]["account"].get("mode")!="synthetic_fixture":
        raise ValueError("synthetic_account_required")
    req["payload"]["product"]=base["request"]["payload"]["product"]
    req["request_sha256"]=digest(req["payload"])
    return _wire(req,"synthetic_wire_fixture")

def build_text_fixture(event,spec,account,*,now):
    """Documented text-only GPT-6 compatibility request; still offline."""
    if event["symbol"]!="BTCUSD":
        raise ValueError("text_fixture_btc_only")
    w=build_synthetic_fixture(event,spec,account,now=now)
    w["mode"]="synthetic_text_wire_fixture"
    del w["body"]["response_format"]
    w["body"]["max_completion_tokens"]=1024
    return w

BTC_COMPATIBILITY_CANDIDATES=("tb-gpt-6","tb-gpt-6-1-sol","tb-claude-sonnet-5-5","tb-gemini-4-hydrogen-high","tb-deepseek-v4-pro")

def parse_fixture(envelope,wire,*,candidate_model=None):
    if wire.get("mode") not in ("offline_wire_preview","synthetic_wire_fixture","synthetic_text_wire_fixture") or wire.get("execution_authorized") is not False:
        raise ValueError("offline_only")
    req=wire["request"]; p=req["payload"]
    if req.get("execution_authorized") is not False or digest(p)!=req["request_sha256"]:
        raise ValueError("request_integrity")
    synthetic=p["account"].get("mode")=="synthetic_fixture"
    if synthetic!=(wire["mode"] in ("synthetic_wire_fixture","synthetic_text_wire_fixture")):
        raise ValueError("fixture_mode_mismatch")
    expected={"model":request_model(req),"messages":[{"role":"system","content":req["system"]},
        {"role":"user","content":canonical(p)}],"response_format":{"type":"json_object"}}
    if wire["mode"]=="synthetic_text_wire_fixture":
        if p["symbol"]!="BTCUSD": raise ValueError("text_fixture_btc_only")
        del expected["response_format"]
        expected["max_completion_tokens"]=1024
    if candidate_model is not None:
        if wire["mode"]!="synthetic_text_wire_fixture" or candidate_model not in BTC_COMPATIBILITY_CANDIDATES:
            raise ValueError("invalid_compatibility_candidate")
        expected["model"]=candidate_model
    if wire["body"]!=expected or wire["endpoint"]!=TOPBILLING_CHAT_URL: raise ValueError("wire_integrity")
    if not isinstance(envelope,dict) or envelope.get("model")!=wire["body"]["model"]:
        raise ValueError("unexpected_model")
    choices=envelope.get("choices")
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict) or choices[0].get("finish_reason")!="stop":
        raise ValueError("incomplete_response")
    message=choices[0].get("message")
    if not isinstance(message,dict) or message.get("role","assistant")!="assistant" or message.get("refusal") or message.get("tool_calls") or message.get("function_call"):
        raise ValueError("unexpected_message")
    raw=message.get("content")
    def pairs(items):
        obj={}
        for key,value in items:
            if key in obj: raise ValueError("duplicate_json_key")
            obj[key]=value
        return obj
    if not isinstance(raw,str) or len(raw)>20000: raise ValueError("invalid_content")
    def reject_constant(value): raise ValueError("nonfinite_json")
    result=json.loads(raw,object_pairs_hook=pairs,parse_constant=reject_constant)
    return validate(result,wire["request"])
