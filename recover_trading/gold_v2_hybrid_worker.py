"""Continuous public quote study. Independent of all trading runtimes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .chart_reference import ReferenceClient
from .gold_v2_reference import observe_reference
from .gold_v2_hybrid import preview,preview_mark,MARK_SOURCE
from .gold_v2_reference import SOURCE
from .gold_v2_mark_hybrid import observe_mark
from .gold_v2_mark_context import ContextCollector,annotate
from .gold_v2_hybrid_validation import HybridJournal
from tradebot.market_data_v3 import public_client

VERSION="gold-v2-hybrid-worker.1"

def reference_read(ref,stamp):
    return stamp,observe_reference(stamp,client=ref)

def mark_read(demo,ref,stamp):
    return stamp,observe_mark(demo,ref,stamp)

def product_info(demo,ref):
    p=demo._request("GET","/v2/products/XAUTUSD")["result"]
    r=ref.get("/v2/products/XAUTUSD")
    for item in (p,r):
        if item.get("symbol")!="XAUTUSD" or type(item.get("id")) is not int or item["id"]<=0:
            raise ValueError("wrong_product")
    return p,r

class Study:
    def __init__(self,journal,demo,ref,product,reference_product,*,clock=time.time,source=SOURCE):
        if source not in (SOURCE,MARK_SOURCE):raise ValueError("unknown_study_source")
        self.source=source
        self.context_collector=ContextCollector(clock=clock) if source==MARK_SOURCE else None
        self.journal=journal;self.demo=demo;self.ref=ref
        self.product=product;self.reference_product=reference_product
        self.clock=clock;self.last_boundary=None;self.future=None;self.reference=None;self.last_signal={}
        self.macro_future=None;self.macro_snapshot=None;self.macro_started=None
    def cycle(self,pool,macro_pool=None):
        now=self.clock();boundary=int(now)//300*300
        out={"version":VERSION,"symbol":"XAUTUSD","mode":"hybrid_research_only",
             "execution_effect":"none","signal_source":self.source,"errors":{}}
        if self.source==MARK_SOURCE and macro_pool is not None:
            if self.macro_future is not None and self.macro_future.done():
                try:self.macro_snapshot=self.macro_future.result()
                except Exception as exc:
                    self.macro_snapshot=None;out["errors"]["macro_refresh"]=type(exc).__name__
                self.macro_future=None
            if self.macro_future is None and (self.macro_started is None or now-self.macro_started>=60):
                self.macro_started=now
                self.macro_future=macro_pool.submit(self.context_collector.refresh)
        if self.future is not None and self.future.done():
            try:self.reference=self.future.result()
            except Exception as exc:
                out["errors"]["reference"]=type(exc).__name__
                self.last_signal={"reference_status":"unavailable","signal_observed_at":int(self.clock())}
            self.future=None
        if self.future is None and self.last_boundary!=boundary:
            self.last_boundary=boundary
            self.future=(pool.submit(mark_read,self.demo,self.ref,int(now)) if self.source==MARK_SOURCE else pool.submit(reference_read,self.ref,int(now)))
        # Demo quote collection is independent of reference history and ticker availability.
        dt=None
        try:
            dt=self.demo.ticker("XAUTUSD")
            out["quote_record"]=self.journal.record_quote(dt,self.product["id"])
        except Exception as exc:out["errors"]["demo_quote"]=type(exc).__name__
        if self.reference is not None:
            stamp,packet=self.reference;self.reference=None
            self.last_signal={}
            report=packet["mark_report" if self.source==MARK_SOURCE else "strict_reference_report"]
            out["reference_status"]=report["status"]
            out["reference_quality"]=report["data_quality"]
            if dt is not None:
                try:
                    rt=self.ref.ticker("XAUTUSD")
                    result=(preview_mark if self.source==MARK_SOURCE else preview)(packet,rt,dt,reference_pid=self.reference_product["id"],
                        demo_pid=self.product["id"],tick_size=self.product["tick_size"],now=self.clock())
                    if self.source==MARK_SOURCE:
                        try:evidence=self.context_collector.project(report,self.macro_snapshot)
                        except Exception as exc:
                            evidence=None;out["errors"]["macro_projection"]=type(exc).__name__
                        result=annotate(result,evidence,now=self.clock())
                        ann=result["macro_annotation"]
                        out["macro_context"]={"status":ann["status"],"candidate_groups":ann["candidate_groups"],
                            "bias":ann.get("evidence",{}).get("fundamentals",{}).get("macro_bias_hypothesis"),
                            "positioning":ann.get("evidence",{}).get("intelligence",{}).get("positioning")}
                    out["hybrid_status"]=result["status"]
                    out["quote_comparison"]=result.get("quotes")
                    out["enrollment"]=self.journal.enroll(result,as_of=stamp)
                except Exception as exc:out["errors"]["hybrid_enrollment"]=type(exc).__name__
            else:out["errors"]["hybrid_enrollment"]="demo_quote_missing"
            if "hybrid_enrollment" in out["errors"]:out["enrollment"]="unavailable"
        for k in ("reference_status","reference_quality","hybrid_status","quote_comparison","enrollment","macro_context"):
            if k in out:self.last_signal[k]=out[k]
        if "reference_status" in out:self.last_signal["signal_observed_at"]=stamp
        out["latest_signal"]=dict(self.last_signal)
        try:out["resolved"]=self.journal.resolve()
        except Exception as exc:out["errors"]["resolution"]=type(exc).__name__
        out["summary"]=self.journal.summary()
        out["timestamp"]=int(self.clock())
        return out

def publish(root,event):
    tmp=root/"hybrid_status.tmp"
    tmp.write_text(json.dumps(event,allow_nan=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,root/"hybrid_status.json")

def run(root,stop,interval,*,source=SOURCE):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/"hybrid.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        journal=HybridJournal(root/"hybrid.sqlite",source=source)
        try:
            demo=public_client();ref=ReferenceClient()
            product,rp=product_info(demo,ref)
            study=Study(journal,demo,ref,product,rp,source=source)
            with ThreadPoolExecutor(max_workers=1) as pool, ThreadPoolExecutor(max_workers=1) as macro_pool:
                while not stop.is_set():
                    started=time.monotonic()
                    event=study.cycle(pool,macro_pool)
                    publish(root,event)
                    stop.wait(max(0,interval-(time.monotonic()-started)))
        finally:journal.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",required=True)
    p.add_argument("--interval",type=float,default=10)
    p.add_argument("--mark-study",action="store_true",help="Dedicated mark-price research directory required")
    args=p.parse_args()
    if not 1<=args.interval<=15:p.error("interval must be between 1 and 15 seconds")
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    run(args.data_dir,stop,args.interval,source=MARK_SOURCE if args.mark_study else SOURCE)
if __name__=="__main__":main()
