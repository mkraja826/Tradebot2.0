"""Sanitized provider response diagnostics. Never retain model text or raw errors."""
import json,re,hashlib
from urllib.error import HTTPError, URLError
from tradebot.ai import PlanError

CODES=frozenset("""offline_only request_integrity fixture_mode_mismatch wire_integrity unexpected_model incomplete_response unexpected_message duplicate_json_key invalid_content nonfinite_json invalid_response_fields response_identity_mismatch missing_rationale wait_must_have_no_plan account_context_unavailable invalid_plan_fields invalid_entry_type invalid_numeric_plan integer_required invalid_protection_geometry missing_management invalid_action""".split())

def classify(exc,phase):
    if isinstance(exc,json.JSONDecodeError): return "invalid_json"
    if type(exc) is ValueError and len(exc.args)==1 and isinstance(exc.args[0],str) and exc.args[0] in CODES:
        return exc.args[0]
    if phase=="transport":
        # Classify only known exception types and fixed client messages.
        # A category never proves the request was not billed or processed.
        code = None
        if isinstance(exc, HTTPError):
            code = exc.code
        elif type(exc) is PlanError and len(exc.args)==1 and isinstance(exc.args[0],str):
            msg=exc.args[0]
            match=re.fullmatch(r"Top Billing API HTTP ([1-5][0-9]{2})",msg)
            if match: code=int(match.group(1))
            elif msg=="Top Billing API network error": return "provider_network_error"
            elif msg in ("Invalid Top Billing API JSON response","Malformed Top Billing response"): return "provider_malformed_response"
            elif msg=="TB_API_KEY is required; store it in a local secret environment": return "provider_credentials_unavailable"
        if code in (401,403): return "provider_authentication_or_permission"
        if code==429: return "provider_rate_limited"
        if type(code) is int and 500<=code<=599: return "provider_server_error"
        if type(code) is int and 400<=code<=499: return "provider_request_rejected"
        if isinstance(exc,TimeoutError) or (isinstance(exc,URLError) and isinstance(exc.reason,TimeoutError)): return "provider_timeout"
        if isinstance(exc,(URLError,OSError)): return "provider_network_error"
        return "transport_outcome_unknown"
    if isinstance(exc,(TypeError,KeyError,AttributeError)): return "unexpected_schema"
    return "unclassified_validation_failure"

def envelope_shape(envelope,model):
    if not isinstance(envelope,dict): return {"object_received":False}
    out={"object_received":True,"model_matches":envelope.get("model")==model}
    returned=envelope.get("model")
    out["model_field_present"]="model" in envelope
    out["model_field_type"]=type(returned).__name__ if type(returned) in (str,int,float,bool,dict,list,type(None)) else "other"
    if isinstance(returned,str):
        out["model_label_sha256"]=hashlib.sha256(returned.encode("utf-8")).hexdigest()
        out["model_label_length"]=len(returned)
        out["model_label_empty"]=not returned.strip()
        out["model_label_matches_after_trim"]=returned.strip()==model
        out["model_label_matches_without_prefix"]=returned.strip()==model.removeprefix("tb-")
    if isinstance(returned,str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}",returned):
        out["returned_model_label"]=returned
    choices=envelope.get("choices")
    out["choice_count"]=len(choices) if isinstance(choices,list) else None
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict): return out
    c=choices[0]
    reason=c.get("finish_reason")
    out["finish_reason"]=reason if isinstance(reason,str) and reason in ("stop","length","content_filter","tool_calls","function_call") else "other_or_missing"
    m=c.get("message")
    if isinstance(m,dict):
        content=m.get("content")
        out.update(content_is_text=isinstance(content,str),content_length=len(content) if isinstance(content,str) else None,
            role_matches=m.get("role","assistant")=="assistant",refusal_present=bool(m.get("refusal")),
            tools_present=bool(m.get("tool_calls") or m.get("function_call")))
    return out

def request_id_digest(value):
    """Correlate provider response headers with exported usage rows without publishing IDs."""
    if isinstance(value,str) and re.fullmatch(r"tb_req_[A-Za-z0-9_-]{8,128}",value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return None
