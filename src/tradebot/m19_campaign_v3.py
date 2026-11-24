"""One finite owner-authorized paper-only campaign; no broker or execution clients."""
import json,sqlite3,time
from pathlib import Path
from contextlib import closing
from tradebot.m19_provider_shadow_v3 import Campaign,dispatch
from tradebot.model_wire_v3 import MODEL_IDS,TOPBILLING_CHAT_URL
from tradebot.messages_wire_v3 import URL
from tradebot.opportunity_journal_v3 import ROUTE
from tradebot.product_context_v3 import collect_specs
from tradebot.research_collector_v3 import atomic_json

LIMIT=20
NAME="m19-provider-campaign-v3.sqlite"
REPORT="m19-provider-campaign-v3.json"

def tick(root,*,transport,spec_reader=collect_specs,clock=time.time):
    root=Path(root)
    c=Campaign(root/NAME,request_limit=LIMIT)
    report={"mode":"paid_paper_only_campaign","checked_at":int(clock()),"markets":{},
            "execution_authorized":False,"orders_submitted":0,"account_basis":"hypothetical"}
    for s in ROUTE:report["markets"][s]={"attempts_this_cycle":0,"status":"no_fresh_opportunity"}
    if c.counts()["remaining"]>0:
        p=root/"opportunities-v3.sqlite"
        if p.is_symlink():raise ValueError("untrusted_source")
        specs=spec_reader()
        with closing(sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            for s in ROUTE:
                item=report["markets"][s]
                if c.counts()["remaining"]<=0:
                    item["status"]="budget_exhausted";continue
                if specs.get(s,{}).get("status")!="ready":
                    item["status"]="product_unavailable";continue
                now=int(clock())
                rows=db.execute("SELECT event_id,payload FROM events WHERE symbol=? AND as_of BETWEEN ? AND ? ORDER BY as_of DESC,event_id LIMIT 100",(s,now-150,now)).fetchall()
                for key,raw in rows:
                    try:
                        e=json.loads(raw)
                        if (e["event_id"],e["symbol"],e["model_if_enabled"])!=(key,s,ROUTE[s]):
                            continue
                        r=dispatch(c,e,specs[s]["data"],transport=transport,clock=clock)
                        item["status"]=r["status"]
                        if r["status"]=="duplicate":continue
                        if r["status"]!="budget_exhausted":item["attempts_this_cycle"]+=1
                        break
                    except (ValueError,KeyError,TypeError):
                        item["status"]="candidate_rejected"
    report["budget"]=c.counts()
    report["status"]="budget_exhausted" if report["budget"]["remaining"]==0 else "active"
    report["checked_at"]=int(clock())
    atomic_json(root/REPORT,report)
    return report

def run_with_provider(root,client):
    """Use the existing owner-local provider client; fixed endpoints and no redirects."""
    p=Path(root)/NAME
    if p.is_symlink() or not p.is_file() or p.stat().st_mode&0o077:raise ValueError("campaign_not_initialized")
    original=client._transport
    def transport(endpoint,body,headers,timeout):
        expected={URL:MODEL_IDS["BTCUSD"],TOPBILLING_CHAT_URL:MODEL_IDS["XAUTUSD"]}
        if endpoint not in expected or body.get("model")!=expected[endpoint] or timeout!=20:
            raise ValueError("unexpected_provider_route")
        if headers!=({"anthropic-version":"2023-06-01"} if endpoint==URL else {}):
            raise ValueError("unexpected_headers")
        def fixed(req,timeout):
            if req.full_url!=endpoint or req.get_method()!="POST":raise ValueError("unexpected_request")
            for k,v in headers.items():req.add_header(k,v)
            return original(req,timeout=timeout)
        client._transport=fixed
        try:return client._call(endpoint,body=body,timeout=timeout)
        finally:client._transport=original
    return tick(root,transport=transport)
