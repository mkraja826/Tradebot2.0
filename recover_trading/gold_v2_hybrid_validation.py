"""Prospective quote-only hybrid study; no orders, fills or candle P&L assumptions."""
import json
import sqlite3
import time
from decimal import Decimal
from .gold_v2_entry_adapter import positive
from .gold_v2_reference import SOURCE
from .entry_quotes import quote_evidence

VERSION="gold-v2-hybrid-validation.1"
HORIZON=3600
MAX_GAP=30
COST_BPS=15

def encode(x):return json.dumps(x,sort_keys=True,allow_nan=False,separators=(",",":"))

class HybridJournal:
    def __init__(self,path,clock=time.time):
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
    def close(self):self.db.close()
    def enroll(self,packet,*,as_of):
        clock_us=int(self.clock()*1000000)
        now=clock_us//1000000
        if type(as_of) is not int or not 0<=now-as_of<=120 or now//300!=as_of//300:
            raise ValueError("not_prospective")
        if packet.get("symbol")!="XAUTUSD" or packet.get("signal_source")!=SOURCE or packet.get("execution_eligible") is not False:
            raise ValueError("wrong_study")
        if packet.get("status")=="hypotheses_observed":
            q=packet["quotes"]
            for k in ("reference_quote_timestamp_us","demo_quote_timestamp_us"):
                if type(q[k]) is not int or not 0<=clock_us-q[k]<=30000000:
                    raise ValueError("stale_enrollment_quote")
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
                        results.append({"family":p["family"],"direction":direction,"exit_reason":reason,
                            "sampled_net_bps":float(net),"hypothetical_entry":str(entry),"sampled_exit_quote":str(px)})
                status="sampled_outcomes" if results else "insufficient_quote_coverage"
                result={"version":VERSION,"status":status,"max_gap_seconds":maxgap,"quote_count":len(rows),
                    "cost_bps_assumed":COST_BPS,"results":results,"fill_verified":False,
                    "limitations":"Sampled mark crossings and book prices only; intragap excursions, liquidity, slippage and funding unknown."}
                self.db.execute("INSERT INTO hybrid_outcomes VALUES(?,?,?)",(boundary,now,encode(result)))
                self.db.execute("UPDATE hybrid_windows SET status=? WHERE boundary=?",(status,boundary))
                count+=1
        return count
    def summary(self):
        return {"version":VERSION,"execution_effect":"none",
                "window_counts":dict(self.db.execute("SELECT status,count(*) FROM hybrid_windows GROUP BY status")),
                "quote_count":self.db.execute("SELECT count(*) FROM hybrid_quotes").fetchone()[0],
                "outcome_count":self.db.execute("SELECT count(*) FROM hybrid_outcomes").fetchone()[0],
                "actual_fills":0,"mode":"quote_sampled_hypotheses"}
