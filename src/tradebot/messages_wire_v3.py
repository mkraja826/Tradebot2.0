"""Isolated Messages compatibility adapter. No credential access or order surface."""
from tradebot.model_wire_v3 import parse_fixture
from tradebot.opportunity_journal_v3 import canonical,digest
URL="https://api.topbilling.in/v1/messages"
MODEL="tb-gpt-6-1-sol"
def build(wire):
    if wire.get("execution_authorized") is not False or wire.get("mode")!="synthetic_text_wire_fixture" or wire["body"]["model"]!=MODEL:
        raise ValueError("invalid_messages_fixture")
    req=wire["request"]
    if req["payload"]["symbol"]!="BTCUSD" or req["payload"]["account"]["mode"]!="synthetic_fixture" or req["execution_authorized"] is not False or digest(req["payload"])!=req["request_sha256"]:
        raise ValueError("invalid_messages_fixture")
    return {"model":MODEL,"max_tokens":1024,"system":req["system"],"messages":[{"role":"user","content":canonical(req["payload"])}]}
def normalize(response):
    if not isinstance(response,dict) or response.get("model")!=MODEL:
        raise ValueError("unexpected_model")
    if response.get("type")!="message" or response.get("role")!="assistant" or response.get("stop_reason")!="end_turn":
        raise ValueError("incomplete_response")
    c=response.get("content")
    if not isinstance(c,list) or len(c)!=1 or not isinstance(c[0],dict) or c[0].get("type")!="text" or not isinstance(c[0].get("text"),str):
        raise ValueError("unexpected_message")
    return {"model":response["model"],"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":c[0]["text"]}}]}
def parse(response,wire,body):
    if body!=build(wire): raise ValueError("wire_integrity")
    return parse_fixture(normalize(response),wire,candidate_model=MODEL)
