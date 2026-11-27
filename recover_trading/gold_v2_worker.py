"""Continuous Gold V2 observation worker, isolated from execution and legacy status.

CLI stays shadow-only. Optional injected controller is for integration testing;
no CLI activation, no AI calls or legacy journal writes by default.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import threading
import time

from tradebot.market_data_v3 import collect,public_client
from .broker import DeltaDemo
from .gold_v2_engine import Bar
from .gold_v2_scan import scan
from .gold_v2_fundamentals import collect_external
from .gold_v2_public_feeds import PublicFeeds
from .gold_v2_validation import Journal
from .gold_v2_entry_adapter import prepare,positive
from .position_preview import observe
from .lifecycle import pages

VERSION="gold-v2-worker.3"
SYMBOL="XAUTUSD"

def account_snapshot(broker,expected_account,*,clock=time.time):
    """Authenticated reads only; require operator-verified isolated Gold demo ID."""
    expected=str(expected_account)
    if not expected.isdigit() or int(expected)<=0 or int(expected)==26679287:
        raise ValueError("invalid_gold_account")
    wallet,=[w for w in broker.wallet()["result"] if w.get("asset_symbol")=="USD"]
    if str(wallet.get("user_id"))!=expected:
        raise ValueError("gold_wallet_mismatch")
    product=broker.product(SYMBOL)
    pid=product.get("id")
    if (product.get("symbol")!=SYMBOL or type(pid) is not int or pid<=0
        or product.get("contract_unit_currency")!="XAUT"
        or product.get("settling_asset",{}).get("symbol")!="USD"
        or product.get("quoting_asset",{}).get("symbol")!="USD"
        or product.get("notional_type")!="vanilla"):
        raise ValueError("unsupported_gold_contract")
    rows=broker.margined_positions(pid)
    if not isinstance(rows,list):raise ValueError("invalid_position_response")
    positions=[]
    from .gold_v2_episode import d
    for p in rows:
        if not isinstance(p,dict) or str(p.get("product_id"))!=str(pid):
            raise ValueError("position_product_mismatch")
        if d(p["size"]):positions.append(p)
    orders,complete=pages(broker.active_orders_page,pid)
    now=int(clock())
    snapshot={"symbol":SYMBOL,"observed":now,"positions":positions,
              "active_orders":orders,"active_orders_complete":complete}
    return observe(snapshot,SYMBOL,now)

class Worker:
    def __init__(self,directory,client,*,broker=None,expected_account=None,allocation_fraction=None,
                 external=None,public_feeds=None,clock=time.time,scanner=scan,collector=collect,controller=None):
        self.root=Path(directory)
        self.root.mkdir(parents=True,exist_ok=True)
        if (broker is None)!=(expected_account is None):
            raise ValueError("account_requires_demo_reader")
        if allocation_fraction is not None:
            if broker is None or positive(allocation_fraction)>1:
                raise ValueError("invalid_preview_allocation")
        self.client=client;self.broker=broker;self.expected_account=expected_account
        self.allocation=allocation_fraction;self.external=external;self.public_feeds=public_feeds
        self.clock=clock;self.scanner=scanner;self.collector=collector
        self.controller=controller
        if controller is not None and (broker is None or controller.broker is not broker or str(expected_account)!=controller.expected):
            raise ValueError("controller_account_mismatch")
        self.lock=None;self.journal=None
    def open(self):
        if self.lock is not None:raise RuntimeError("already_open")
        lock=(self.root/"worker.lock").open("a")
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.journal=Journal(self.root/"validation.sqlite",clock=self.clock)
        except BaseException:
            lock.close()
            raise
        self.lock=lock
    def close(self):
        try:
            if self.journal is not None:self.journal.close()
        finally:
            self.journal=None
            if self.lock is not None:self.lock.close()
            self.lock=None
    def publish(self,event):
        temp=self.root/"gold_v2_status.tmp"
        temp.write_text(json.dumps(event,allow_nan=False,separators=(",",":")),encoding="utf-8")
        temp.replace(self.root/"gold_v2_status.json")
    def cycle(self):
        if self.journal is None:raise RuntimeError("worker_not_open")
        started=time.monotonic()
        event={"version":VERSION,"symbol":SYMBOL,"mode":"shadow","execution_effect":"none",
               "execution_enabled":False,"ai_calls":0,"errors":{}}
        report=None
        bars=[]
        try:
            report=self.scanner(self.client,int(self.clock()),external=self.external,
                                public_feeds=self.public_feeds,clock=self.clock)
            if report.get("symbol")!=SYMBOL:raise ValueError("wrong_scan_symbol")
            event["market"]={k:report.get(k) for k in ("version","status","as_of","decision_as_of","regime","data_quality","feed_health")}
            event["candidate_count"]=len(report.get("candidates",[]))
            event["candidates"]=[{"family":c["family"],"direction":c["direction"]} for c in report.get("candidates",[])]
            features=report.get("features",{})
            event["technical"]={str(sec):{k:row.get(k) for k in ("ema","atr","direction","rsi14","adx","rolling_vwap20","relative_volume20","structure")} for sec in (300,900,3600) if (row:=features.get(sec,features.get(str(sec)))) is not None}
            intel=report.get("intelligence",{})
            fundamental=report.get("fundamentals",{})
            event["intelligence"]={"version":intel.get("version"),"technical_direction":intel.get("technical",{}).get("direction"),"macro_direction":intel.get("macro",{}).get("direction"),"macro_bias":fundamental.get("macro_bias_hypothesis"),"macro":{k:fundamental.get("macro",{}).get(k) for k in ("broad_dollar_5obs_pct","real_yield_5obs_bp")},"candidates":[{k:c.get(k) for k in ("family","direction","support_index","observed_groups","expected_groups")} for c in intel.get("candidates",[])]}
            event["enrollment"]=self.journal.enroll(report)
        except Exception as exc:
            event["errors"]["scan_or_enrollment"]=type(exc).__name__
        # Resolution is independent of the current entry scan.
        try:
            stamp=int(self.clock())
            raw=self.collector(self.client,SYMBOL,as_of=stamp,frames=("5m",),count=400)
            if raw.get("symbol")!=SYMBOL or raw.get("as_of")!=stamp:raise ValueError("wrong_resolution_market")
            item=raw.get("frames",{}).get("5m",{})
            event["resolution_feed"]=item.get("status","unavailable")
            if item.get("status")=="ready":
                bars=[Bar(b["time"]+300,b["open"],b["high"],b["low"],b["close"],b["volume"]) for b in item["bars"]]
                event["resolved_windows"]=self.journal.resolve(bars)
        except Exception as exc:event["errors"]["resolution"]=type(exc).__name__
        try:
            summary=self.journal.summary()
            event["validation"]={k:summary[k] for k in ("window_counts","observed_nonoverlapping_windows","target_windows","target_reached")}
            event["validation"]["combined_comparisons"]=summary.get("combined_comparisons",[])[:200]
            event["validation"]["combined_comparisons_total"]=len(summary.get("combined_comparisons",[]))
        except Exception as exc:event["errors"]["validation"]=type(exc).__name__
        if self.broker is not None:
            try:
                view=account_snapshot(self.broker,self.expected_account,clock=self.clock)
                event["account"]={k:view.get(k) for k in ("position_state","bracket_state","observed")}
                if (report is not None and self.allocation is not None
                    and view["position_state"]=="flat" and view["bracket_state"]=="no_orders_observed"):
                    proposal,_=prepare(self.broker,report,expected_gold_account=self.expected_account,
                                       allocation_fraction=self.allocation,clock=self.clock)
                    # No quantities, balances, account IDs or receipts in public status.
                    event["entry_preview"]={"status":proposal["status"]}
            except Exception as exc:event["errors"]["account_read"]=type(exc).__name__
        if self.controller is not None:
            try:
                result=self.controller.cycle(report if report is not None else {"symbol":SYMBOL,"status":"scan_error"},bars)
                event["controller"]={k:result.get(k) for k in ("status","execution_status","management_status","attempted")}
                event["execution_enabled"]=self.controller.enabled
                event["mode"]="demo_controller" if self.controller.enabled else "shadow"
                if self.controller.enabled:event["execution_effect"]="demo_dispatch_possible_not_fill_confirmation"
            except Exception as exc:
                event["errors"]["controller"]=type(exc).__name__
                # A failure after dispatch cannot be described as no execution.
                if self.controller.enabled:
                    event["execution_enabled"]=True
                    event["mode"]="demo_controller"
                    event["execution_effect"]="unknown_requires_reconciliation"
        event["status"]="degraded" if event["errors"] else "observing"
        event["timestamp"]=int(self.clock())
        event["cycle_ms"]=round((time.monotonic()-started)*1000)
        self.publish(event)
        return event
    def run(self,stop,interval,*,once=False):
        if not math.isfinite(interval) or interval<=0:raise ValueError("invalid_interval")
        self.open()
        try:
            while not stop.is_set():
                started=time.monotonic()
                self.cycle()
                if once:break
                stop.wait(max(0,interval-(time.monotonic()-started)))
        finally:self.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",required=True,help="Dedicated Gold V2 directory; not legacy status path")
    p.add_argument("--interval",type=float,default=60)
    p.add_argument("--once",action="store_true")
    p.add_argument("--fundamentals",action="store_true")
    p.add_argument("--public-feeds",action="store_true")
    p.add_argument("--gold-demo-account",help="Operator-verified isolated Gold demo account ID")
    p.add_argument("--preview-allocation",type=float)
    args=p.parse_args()
    broker=None
    if args.gold_demo_account is not None:
        key=os.environ.get("RECOVER_GOLD_DEMO_KEY");secret=os.environ.get("RECOVER_GOLD_DEMO_SECRET")
        btc_key=os.environ.get("RECOVER_BTC_DEMO_KEY")
        if not key or not secret or not btc_key or key==btc_key:
            p.error("Distinct configured BTC and Gold demo credentials required")
        broker=DeltaDemo(key,secret)
    elif args.preview_allocation is not None:p.error("Allocation preview requires demo account reads")
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    worker=Worker(args.data_dir,public_client(),broker=broker,expected_account=args.gold_demo_account,
                  allocation_fraction=args.preview_allocation,external=collect_external if args.fundamentals else None,
                  public_feeds=PublicFeeds() if args.public_feeds else None)
    worker.run(stop,args.interval,once=args.once)

if __name__=="__main__":main()
