"""Read-only M6 scanner, independently journal one-of-N market candidates."""
from pathlib import Path
from time import time
from collections import Counter
import json
from tradebot.feature_snapshot_v3 import snapshot
from tradebot.bitcoin_strategies_v3 import scan_btc
from tradebot.gold_strategies_v3 import scan_gold
from tradebot.gold_macro_v3 import features as macro_features
from tradebot.gold_stress_v3 import features as stress_features,URLS as STRESS_URLS
from tradebot.news_context_v3 import fomc_active,URLS as NEWS_URLS
from tradebot.opportunity_journal_v3 import OpportunityJournal
from tradebot.decision_learning_context_v3 import freeze as freeze_learning
from tradebot.m21_adaptive_memory_v3 import freeze as freeze_paper_memory
from tradebot.research_collector_v3 import atomic_json

SCANNERS={"BTCUSD":scan_btc,"XAUTUSD":scan_gold}
EXTERNAL={"BTCUSD":("btc_spot",),"XAUTUSD":("gold_token_proxy","yields","broad_dollar","bls_calendar")}

def context_for(symbol,stamp,market,external,observed_at):
    refs={}
    for key in (*EXTERNAL[symbol],*((*NEWS_URLS,*STRESS_URLS) if symbol=="XAUTUSD" else ())):
        item=external.get(key,{})
        t=item.get("observed_at")
        maxage=120 if key in ("btc_spot","gold_token_proxy") else 21600+600
        if key in NEWS_URLS: maxage=420
        if item.get("status")=="ready" and isinstance(t,(int,float)) and 0<=observed_at-t<=maxage:
            refs[key]=item
        else: refs[key]={"status":"unavailable"}
    return {"symbol":symbol,"as_of":stamp,"context_observed_at":observed_at,
            "market":market,"external":refs,"thresholds":"uncalibrated_research",
            "mode":"shadow"}

def tick(root,*,now=None):
    root=Path(root); now=int(time()) if now is None else now
    status={"mode":"shadow","checked_at":now,"markets":{},"ai_requests":0,"orders_submitted":0}
    try:
        capture=json.loads((root/"collector-status.json").read_text())
        stamp=capture["as_of"]
        if type(stamp) is not int or not 0<=now-stamp<=150: raise ValueError("collector_stale")
    except (OSError,KeyError,TypeError,ValueError):
        status["status"]="collector_unavailable"
        atomic_json(root/"scanner-status.json",status)
        return status
    try: external=json.loads((root/"external-context.json").read_text())
    except (OSError,ValueError): external={}
    journal=OpportunityJournal(root/"opportunities-v3.sqlite")
    status["as_of"]=stamp
    for symbol,scanner in SCANNERS.items():
        try:
            s=snapshot(root/"market-v3.sqlite",stamp,symbols=(symbol,))
            context=context_for(symbol,stamp,s["markets"][symbol],external,now)
            if symbol=="XAUTUSD":
                s["markets"][symbol]["context"].update(macro_features(context["external"],observed_at=now))
                s["markets"][symbol]["context"].update(stress_features(context["external"],observed_at=now))
                item=s["markets"][symbol]["frames"].get("15m",{})
                if item.get("status")=="ready":
                    item["fomc_post_statement"]=fomc_active(context["external"].get("fomc_release",{}),now=now,closed_at=item["closed_at"],frame_seconds=900)
            scan=scanner(s)
            if scan["signals"]:
                context["strategy_learning"]=freeze_learning(root,symbol,scan["signals"],context,now=now)
                context["paper_learning"]=freeze_paper_memory(root,symbol,scan["signals"],context,now=now)
            event=journal.record(scan,context)
            status["markets"][symbol]={"status":"ready","evaluations":dict(Counter(x["status"] for x in scan["results"])),
                "signals":scan["signals"],"deferred":len(scan["deferred"]),
                "candidate":scan["trigger_ai"],"new_event_id":event["event_id"] if event else None,
                "new_signals":len(event["new_signals"]) if event else 0}
        except Exception as e:
            status["markets"][symbol]={"status":"unavailable","reason":type(e).__name__}
    status["journal"]=journal.counts()
    status["status"]="ready" if all(v["status"]=="ready" for v in status["markets"].values()) else "degraded"
    atomic_json(root/"scanner-status.json",status)
    return status

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--directory",type=Path,required=True)
    print(json.dumps(tick(p.parse_args().directory),sort_keys=True))
