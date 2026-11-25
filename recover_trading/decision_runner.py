"""Run public signal scanning and optionally request paid AI proposals. No orders."""
import argparse
import json
import time
from .scanner import scan_once
from .decision import DecisionJournal, Provider, configured_models, evaluate_report
from tradebot.market_data_v3 import MARKETS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",default="data/recover-market.sqlite")
    p.add_argument("--journal",default="data/recover-decisions.sqlite")
    p.add_argument("--symbol",choices=MARKETS,action="append")
    p.add_argument("--interval",type=float,default=0)
    p.add_argument("--request-ai",action="store_true",help="Submit potentially billable proposals")
    a=p.parse_args()
    if a.interval<0:
        p.error("interval must be non-negative")
    models=configured_models()
    symbols=a.symbol or MARKETS
    provider=Provider()
    if a.request_ai and (not provider.key or any(not models[s] for s in symbols)):
        p.error("Set TB_API_KEY and the selected market model variables in the runtime environment")
    journal=DecisionJournal(a.journal) if a.request_ai else None
    while True:
        scan=scan_once(a.database,symbols=symbols,include_context=a.request_ai)
        results={}
        for s,r in scan["markets"].items():
            if r.get("status")=="scan_error":
                results[s]=r
            elif a.request_ai:
                try:
                    results[s]=evaluate_report(r,journal,provider,models)
                except Exception as exc:
                    results[s]={"status":"decision_error","reason":type(exc).__name__}
            else:
                results[s]={"status":"preview","signals":r["signals"],"coverage":r["coverage"],"ai_calls":0}
        print(json.dumps({"markets":results,"orders_submitted":0},allow_nan=False),flush=True)
        if not a.interval:
            break
        time.sleep(a.interval)


if __name__=="__main__":
    main()
