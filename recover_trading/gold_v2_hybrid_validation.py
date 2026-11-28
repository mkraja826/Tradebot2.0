"""Prospective quote-only hybrid study; no orders, fills or candle P&L assumptions."""
import json
import sqlite3
import time
from decimal import Decimal
from .gold_v2_entry_adapter import positive
from .gold_v2_reference import SOURCE
from .gold_v2_hybrid import MARK_SOURCE
from .entry_quotes import quote_evidence
from .gold_v2_quote_management import compare as compare_management, VERSION as MANAGEMENT_VERSION, POLICIES

VERSION="gold-v2-hybrid-validation.1"
HORIZON=3600
MAX_GAP=30
COST_BPS=15

def encode(x):return json.dumps(x,sort_keys=True,allow_nan=False,separators=(",",":"))

class HybridJournal:
    def __init__(self,path,clock=time.time,*,source=SOURCE):
        if source not in (SOURCE,MARK_SOURCE):raise ValueError("unknown_study_source")
        self.source=source
        self.clock=clock
        self.db=sqlite3.connect(path,timeout=10)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS hybrid_windows(
            boundary INTEGER PRIMARY KEY, enrolled INTEGER NOT NULL,
            evidence TEXT NOT NULL,status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hybrid_quotes(
            stamp INTEGER PRIMARY KEY,observed INTEGER NOT NULL,evidence TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hybrid_outcomes(
            boundary INTEGER PRIMARY KEY,resolved INTEGER NOT NULL,evidence TEXT NOT NULL);
        """)
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("CREATE TABLE IF NOT EXISTS hybrid_study (id INTEGER PRIMARY KEY CHECK(id=1),source TEXT NOT NULL)")
                existing=self.db.execute("SELECT source FROM hybrid_study WHERE id=1").fetchone()
                if existing is None:
                    # All legacy unbound windows belong to the original traded-price cohort.
                    populated=any(self.db.execute("SELECT 1 FROM "+table+" LIMIT 1").fetchone()
                                  for table in ("hybrid_windows","hybrid_quotes","hybrid_outcomes"))
                    if populated and source!=SOURCE:raise ValueError("unbound_legacy_study")
                    self.db.execute("INSERT INTO hybrid_study VALUES(1,?)",(source,))
                elif existing[0]!=source:raise ValueError("study_source_mismatch")
        except BaseException:
            self.db.close()
            raise
    def close(self):self.db.close()
    def enroll(self,packet,*,as_of):
        clock_us=int(self.clock()*1000000)
        now=clock_us//1000000
        if type(as_of) is not int or not 0<=now-as_of<=120 or now//300!=as_of//300:
            raise ValueError("not_prospective")
        if packet.get("symbol")!="XAUTUSD" or packet.get("signal_source")!=self.source or packet.get("execution_eligible") is not False:
            raise ValueError("wrong_study")
        if packet.get("status")=="hypotheses_observed":
            q=packet["quotes"]
            for k in ("reference_quote_timestamp_us","demo_quote_timestamp_us"):
                if type(q[k]) is not int or not 0<=clock_us-q[k]<=30000000:
                    raise ValueError("stale_enrollment_quote")
        if self.source==MARK_SOURCE and packet.get("status")=="hypotheses_observed" and all("translated_atr" in p for p in packet["hypotheses"]):
            packet=dict(packet,management_version=MANAGEMENT_VERSION)
        boundary=as_of//300*300
        status="enrolled" if packet.get("status")=="hypotheses_observed" and any(p.get("mark_geometry_compatible") is True for p in packet["hypotheses"]) else "not_enrolled"
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM hybrid_windows WHERE boundary=?",(boundary,)).fetchone():
                return "duplicate"
            if status=="enrolled" and self.db.execute("SELECT 1 FROM hybrid_windows WHERE status='enrolled' AND enrolled+?>?",(HORIZON,now)).fetchone():
                status="overlap_excluded"
            self.db.execute("INSERT INTO hybrid_windows VALUES(?,?,?,?)",(boundary,now,encode(packet),status))
        return status
    def record_quote(self,ticker,pid):
        now=int(self.clock()*1000000)
        q=quote_evidence(ticker,"XAUTUSD",pid,now)
        if q["status"]!="fresh_book" or not q.get("mark_price"):return "unavailable"
        raw=encode(q)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS hybrid_market (id INTEGER PRIMARY KEY CHECK(id=1),product_id INTEGER NOT NULL)")
            self.db.execute("INSERT OR IGNORE INTO hybrid_market VALUES(1,?)",(pid,))
            if self.db.execute("SELECT product_id FROM hybrid_market WHERE id=1").fetchone()[0]!=pid:
                raise ValueError("product_changed")
            existing=self.db.execute("SELECT evidence FROM hybrid_quotes WHERE stamp=?",(q["timestamp_us"],)).fetchone()
            if existing:
                # Quote age changes on repeated observations; compare only prices.
                old=json.loads(existing[0])
                keys=("best_bid","best_ask","mark_price")
                if any(old[k]!=q[k] for k in keys):raise ValueError("conflicting_quote")
                return "duplicate"
            self.db.execute("INSERT INTO hybrid_quotes VALUES(?,?,?)",(q["timestamp_us"],now,raw))
        return "recorded"
    def resolve(self):
        now=int(self.clock());count=0
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for boundary,enrolled,raw in self.db.execute("SELECT boundary,enrolled,evidence FROM hybrid_windows WHERE status='enrolled' AND enrolled+?<=?",(HORIZON,now)).fetchall():
                packet=json.loads(raw)
                start=max(enrolled*1000000,packet["quotes"]["demo_quote_timestamp_us"]);end=start+HORIZON*1000000
                if now*1000000<end:continue
                rows=self.db.execute("SELECT stamp,observed,evidence FROM hybrid_quotes WHERE stamp>? AND stamp<=? AND observed<=? ORDER BY stamp",(start,end,end)).fetchall()
                # No interpolation: sparse sampling cannot establish a stop/target path.
                times=[start]+[r[0] for r in rows]+[end]
                maxgap=max(b-a for a,b in zip(times,times[1:]))/1000000
                results=[]
                if maxgap<=MAX_GAP and rows:
                    for p in packet["hypotheses"]:
                        if p.get("mark_geometry_compatible") is not True:continue
                        direction=p["direction"];sign=1 if direction=="LONG" else -1
                        entry=positive(p["demo_book_entry_reference"]);sl=positive(p["hypothetical_stop"]);tp=positive(p["hypothetical_target"])
                        exitq=None;reason="horizon_sample"
                        for stamp,observed,qraw in rows:
                            q=json.loads(qraw);mark=positive(q["mark_price"])
                            exitq=q
                            if sign*(mark-sl)<=0:reason="sampled_stop";break
                            if sign*(mark-tp)>=0:reason="sampled_target";break
                        px=positive(exitq["best_bid"] if sign==1 else exitq["best_ask"])
                        net=sign*(px-entry)/entry*10000-Decimal(COST_BPS)
                        item={"family":p["family"],"direction":direction,"exit_reason":reason,
                            "sampled_net_bps":float(net),"hypothetical_entry":str(entry),"sampled_exit_quote":str(px)}
                        if packet.get("management_version")==MANAGEMENT_VERSION:
                            try:item["management"]=compare_management(p,[(t,json.loads(q)) for t,_,q in rows])
                            except (ValueError,KeyError,ArithmeticError,TypeError):item["management"]={"status":"invalid_evidence"}
                        results.append(item)
                status="sampled_outcomes" if results else "insufficient_quote_coverage"
                result={"version":VERSION,"status":status,"max_gap_seconds":maxgap,"quote_count":len(rows),
                    "cost_bps_assumed":COST_BPS,"results":results,"fill_verified":False,
                    "limitations":"Sampled mark crossings and book prices only; intragap excursions, liquidity, slippage and funding unknown."}
                self.db.execute("INSERT INTO hybrid_outcomes VALUES(?,?,?)",(boundary,now,encode(result)))
                self.db.execute("UPDATE hybrid_windows SET status=? WHERE boundary=?",(status,boundary))
                count+=1
        return count
    def summary(self):
        by_family={};by_macro={};paired={}
        for raw,window in self.db.execute("SELECT o.evidence,w.evidence FROM hybrid_outcomes o JOIN hybrid_windows w ON o.boundary=w.boundary"):
            result=json.loads(raw)
            evidence=json.loads(window)
            model_version=evidence.get("model_version") or "unversioned"
            annotation=evidence.get("macro_annotation",{})
            groups={(x["family"],x["direction"]):x["macro_group"] for x in annotation.get("candidate_groups",[]) if x.get("macro_group") in ("aligned","opposed","neutral","unknown")}
            for p in result.get("results",[]):
                key=(p["family"],p["direction"],model_version)
                acc=by_family.setdefault(key,[0,0,0.0])
                acc[0]+=1;acc[1]+=p["sampled_net_bps"]>0;acc[2]+=p["sampled_net_bps"]
                macro=by_macro.setdefault((*key,groups.get(key[:2],"unknown")),[0,0,0.0])
                macro[0]+=1;macro[1]+=p["sampled_net_bps"]>0;macro[2]+=p["sampled_net_bps"]
                management=p.get("management",{})
                if management.get("version")==MANAGEMENT_VERSION:
                    for cost,variants in management["results"].items():
                        if set(variants)!=set(POLICIES):continue
                        fixed=variants["fixed"]["net_bps_initial_notional"]
                        for policy in POLICIES[1:]:
                            variant=variants[policy]["net_bps_initial_notional"]
                            a=paired.setdefault((*key,MANAGEMENT_VERSION,cost,policy),[0,0.0,0.0,0])
                            a[0]+=1;a[1]+=fixed;a[2]+=variant;a[3]+=variant>fixed
        comparisons=[{"family":k[0],"direction":k[1],"samples":v[0],
                      "positive_samples":v[1],"mean_sampled_net_bps":v[2]/v[0],"model_version":k[2]}
                     for k,v in sorted(by_family.items())]
        strata=[{"family":k[0],"direction":k[1],"macro_group":k[3],"model_version":k[2],"samples":v[0],
                 "positive_samples":v[1],"mean_sampled_net_bps":v[2]/v[0]} for k,v in sorted(by_macro.items())]
        pairs=[{"family":k[0],"direction":k[1],"model_version":k[2],"management_version":k[3],
                "cost_bps":int(k[4]),"policy":k[5],"paired_samples":a[0],
                "mean_fixed_net_bps":a[1]/a[0],"mean_variant_net_bps":a[2]/a[0],
                "mean_paired_difference_bps":(a[2]-a[1])/a[0],"improved_samples":a[3]} for k,a in sorted(paired.items())]
        return {"version":VERSION,"execution_effect":"none","management_pairs":pairs,"macro_strata":strata,"sampled_comparisons":comparisons,"signal_source":self.source,
                "window_counts":dict(self.db.execute("SELECT status,count(*) FROM hybrid_windows GROUP BY status")),
                "quote_count":self.db.execute("SELECT count(*) FROM hybrid_quotes").fetchone()[0],
                "outcome_count":self.db.execute("SELECT count(*) FROM hybrid_outcomes").fetchone()[0],
                "actual_fills":0,"mode":"quote_sampled_hypotheses"}
