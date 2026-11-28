"""Dedicated demo mark execution loop; independent of the research worker.

No live installation or automatic enablement. The local owner lock is
cooperative; operator must establish exclusive ownership before execution.
"""
import argparse,json,math,os,signal,threading,time
from pathlib import Path
from contextlib import ExitStack
from .broker import DeltaDemo
from .engine import Journal
from .gold_v2_episode import EpisodeJournal
from .gold_v2_controller import outstanding
from .gold_v2_runtime import config,owner_lock,bind_journal,verify_start,LOCK_ROOT
from .gold_v2_mark_controller import MarkController
from .gold_v2_mark_hybrid import observe_mark
from .gold_v2_mark_aggregation import collect
from .gold_v2_hybrid import MARK_SOURCE
from .chart_reference import ReferenceClient
from tradebot.market_data_v3 import public_client

VERSION="gold-v2-mark-runtime.1"
DATA_ROOT=Path("/var/lib/recover-trading/gold-v2-mark-execution")

class Loop:
    def __init__(self,controller,demo,reference,root,*,clock=time.time):
        self.controller=controller;self.demo=demo;self.reference=reference
        self.root=Path(root);self.clock=clock;self.last_entry_boundary=None

    def cycle(self):
        now=int(self.clock());boundary=now//300*300
        event={"version":VERSION,"symbol":"XAUTUSD","mode":"demo_mark_execution",
               "execution_enabled":self.controller.enabled,"signal_source":MARK_SOURCE,
               "execution_effect":"demo_dispatch_possible_not_fill_confirmation" if self.controller.enabled else "none",
               "errors":{}}
        try:
            owned=outstanding(self.controller.episodes)
            if owned:
                # Owned exposure always has priority. Do not require production
                # data or macro services to reconcile existing exchange orders.
                bars=[]
                try:
                    bars=collect(lambda p:self.demo._request("GET","/v2/history/candles",params=p)["result"],
                                 "5m",300,boundary,750)
                except Exception as exc:event["errors"]["demo_history"]=type(exc).__name__
                result=self.controller.cycle({},bars,demo_as_of=now)
            elif boundary==self.last_entry_boundary:
                result={"status":"entry_boundary_already_observed"}
            else:
                reference=observe_mark(self.demo,self.reference,now)
                report=reference["mark_report"]
                if report["status"]!="observed" or not report.get("candidates"):
                    result={"status":report["status"] if report["status"]!="observed" else "no_candidate"}
                    if report["status"]=="observed":self.last_entry_boundary=boundary
                else:
                    p=self.reference.get("/v2/products/XAUTUSD")
                    if p.get("symbol")!="XAUTUSD" or type(p.get("id")) is not int or p["id"]<=0:
                        raise ValueError("wrong_reference_product")
                    ticker=self.reference.ticker("XAUTUSD")
                    result=self.controller.cycle(reference,ref_ticker=ticker,reference_pid=p["id"])
                    # Transient quote/network failures may retry inside the
                    # original freshness window; durable seeds prevent replay.
                    if result["status"] in ("entry_dispatch","entry_bar_already_reserved","conflicting_candidates",
                                            "conflicting_bracket_parameters","incompatible_bracket"):
                        self.last_entry_boundary=boundary
            event["controller"]={k:result.get(k) for k in ("status","execution_status","management_status","attempted","post_entry_observation")}
        except Exception as exc:
            event["errors"]["cycle"]=type(exc).__name__
            if self.controller.enabled:event["execution_effect"]="unknown_requires_reconciliation"
        event["timestamp"]=int(self.clock())
        tmp=self.root/"mark_execution_status.tmp"
        tmp.write_text(json.dumps(event,allow_nan=False),encoding="utf-8")
        tmp.replace(self.root/"mark_execution_status.json")
        return event

    def run(self,stop,interval):
        while not stop.is_set():
            started=time.monotonic()
            self.cycle()
            stop.wait(max(0,interval-(time.monotonic()-started)))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight",action="store_true")
    mode.add_argument("--execute-demo",action="store_true")
    p.add_argument("--legacy-gold-stopped",action="store_true")
    p.add_argument("--interval",type=float,default=15)
    args=p.parse_args()
    if not math.isfinite(args.interval) or not 10<=args.interval<=60:p.error("interval must be 10 to 60 seconds")
    if args.execute_demo and not args.legacy_gold_stopped:p.error("verified Gold handoff required")
    try:
        gold,btc,main_id,key,secret,bkey,bsecret,allocation=config(os.environ)
        broker=DeltaDemo(key,secret);btc_broker=DeltaDemo(bkey,bsecret)
        with owner_lock(LOCK_ROOT,gold),ExitStack() as stack:
            DATA_ROOT.mkdir(parents=True,exist_ok=True)
            orders=Journal(DATA_ROOT/"orders.sqlite");stack.callback(orders.close)
            episodes=EpisodeJournal(DATA_ROOT/"episodes.sqlite");stack.callback(episodes.close)
            bind_journal(orders,episodes,gold)
            state=verify_start(broker,btc_broker,gold,btc,main_id,episodes)
            if any(s.get("signal_provenance",{}).get("signal_source")!=MARK_SOURCE for _,s in outstanding(episodes)):
                raise ValueError("wrong_episode_source")
            print(json.dumps(state),flush=True)
            if args.preflight:return 0
            controller=MarkController(broker,orders,episodes,expected_account=gold,
                                      allocation_fraction=allocation,enabled=True)
            stop=threading.Event()
            for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
            Loop(controller,public_client(),ReferenceClient(),DATA_ROOT).run(stop,args.interval)
            return 0
    except Exception as exc:
        print(json.dumps({"version":VERSION,"status":"runtime_stopped","error":type(exc).__name__,
                          "execution_effect":"unknown_if_dispatch_previously_enabled" if args.execute_demo else "none"}),flush=True)
        return 1
if __name__=="__main__":raise SystemExit(main())
