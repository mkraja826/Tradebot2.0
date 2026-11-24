"""Offline outcome projection, never a substitute provider reply or order request."""
from tradebot.model_wire_v3 import parse_fixture,MODEL_IDS
from tradebot.messages_wire_v3 import parse as parse_messages
from tradebot.opportunity_journal_v3 import digest

def review(wire,envelope,*,now,messages_body=None):
    out=dict(mode="offline_decision_outcome",action="WAIT",origin="local_failure_wait",
             provider_response_validated=False,execution_authorized=False,orders_submitted=0,
             retry_authorized=False,request_sha256=None,response_sha256=None)
    stage="request"
    try:
        req=wire["request"];p=req["payload"];s=p["symbol"]
        if wire["execution_authorized"] is not False or req["execution_authorized"] is not False:
            raise ValueError("offline_only")
        if s not in MODEL_IDS or digest(p)!=req["request_sha256"]:
            raise ValueError("request_integrity")
        out["request_sha256"]=req["request_sha256"]
        stage="freshness"
        if type(now) is not int or type(p["as_of"]) is not int or not 0<=now-p["as_of"]<=150:
            raise ValueError("stale_request")
        spec=p["product"]
        if spec["symbol"]!=s or spec["source"]!="delta_demo_public_product" or not 0<=now-spec["observed_at"]<=300:
            raise ValueError("product_context")
        stage="response"
        if envelope is None:return dict(out,status="response_unavailable",failure_stage=stage)
        if wire["body"]["model"]!=MODEL_IDS[s]:
            raise ValueError("wrong_model")
        r=parse_messages(envelope,wire,messages_body) if messages_body is not None else parse_fixture(envelope,wire)
        return dict(out,status="validated_offline_response",action=r["action"],
                    origin="validated_fixture_response",provider_response_validated=True,
                    response_sha256=digest(r))
    except (ValueError,KeyError,TypeError,AttributeError,ArithmeticError,RecursionError) as exc:
        return dict(out,status="invalid_or_stale_response",failure_stage=stage,failure_type=type(exc).__name__)
