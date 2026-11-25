"""Matched candle-only registry comparison; isolated from execution."""
import argparse,hashlib,json,sqlite3,tempfile,time
from pathlib import Path
from contextlib import closing
from collections import Counter
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
from tradebot.market_store_v3 import MarketStore
from tradebot.feature_snapshot_v3 import snapshot
from .reference_history import candles
from .backtest import SCANNERS
from .direction import direction_for,REGISTRY

VERSION="reference-strategy-v1"
def targets(symbol):
    return {"5m":900 if symbol=="XAUTUSD" else 600,"15m":250,"1h":250,"4h":250,"1d":180 if symbol=="XAUTUSD" else 250}

def scan_windows(symbol,at,windows):
    # Temporary candle-only stores prevent demo quotes, derivatives or
    # external context leaking into either source.
    with tempfile.TemporaryDirectory(prefix="recover-candle-compare-") as tmp:
        store=MarketStore(Path(tmp)/"candles.sqlite")
        for frame,bars in windows.items():
            store.candles(symbol,frame,bars,as_of=at)
        data=snapshot(store.path,at,symbols=(symbol,),candle_as_of=at)
        report=SCANNERS[symbol](data)
        report["market_context"]=data["markets"][symbol]
        return report

def compare_reports(demo,reference):
    symbol=demo["symbol"]
    if reference["symbol"]!=symbol or reference["as_of"]!=demo["as_of"]:
        raise ValueError("comparison identity mismatch")
    def index(r):return {(x["id"],x["frame"]):x for x in r["results"]}
    d,r=index(demo),index(reference)
    if d.keys()!=r.keys():raise ValueError("registry mismatch")
    rows=[];common=set();counts=Counter()
    for key in sorted(d):
        a,b=d[key],r[key]
        av=a["status"] in ("triggered","no_signal")
        bv=b["status"] in ("triggered","no_signal")
        ad=sorted(a.get("directions",[])) if av else None
        bd=sorted(b.get("directions",[])) if bv else None
        if av and bv:
            common.add(key)
            state="agree_active" if ad==bd and ad else "agree_inactive" if ad==bd else "different"
        elif av:state="demo_only_available"
        elif bv:state="reference_only_available"
        else:state="both_unavailable"
        counts[state]+=1
        rows.append({"id":key[0],"frame":key[1],"name":a["name"],"comparison":state,
                     "demo":ad,"reference":bd,"demo_missing":a.get("missing",[]),"reference_missing":b.get("missing",[])})
    def summary(report,matched=False):
        signals=[s for s in report["signals"] if not matched or (s["id"],s["frame"]) in common]
        direction=direction_for({**report,"signals":signals})
        evaluable={x["id"] for x in report["results"] if x["status"] in ("triggered","no_signal")}
        return {"direction":direction["direction"],"long_score":direction["long_score"],"short_score":direction["short_score"],
                "regime":direction["regime"],"evaluable_rules":len({k[0] for k in common}) if matched else len(evaluable),
                "signals":signals,"active_rules":len({s["id"] for s in signals})}
    rules,deferred=REGISTRY[symbol]
    return {"implemented_rules":len(rules),"deferred":deferred,"rule_frame_rows":len(rows),
            "comparable_rule_frames":len(common),"comparison_counts":dict(counts),
            "demo":summary(demo),"reference":summary(reference),
            "matched_demo":summary(demo,True) if common else None,
            "matched_reference":summary(reference,True) if common else None,"rows":rows}

def matched_cutoff(db,symbol,now):
    expected=now//300*300
    last=db.execute("SELECT max(stamp) FROM samples WHERE symbol=? AND series='candle:5m' AND stamp<?",(symbol,expected)).fetchone()[0]
    return min(expected,last+300) if type(last) is int and last%300==0 else expected

def run(root,symbol,now,fetch=candles):
    if symbol not in MARKETS or type(now) is not int:raise ValueError("invalid market")
    root=Path(root)/symbol
    expected=now//300*300
    demo={};reference={};coverage={}
    with closing(sqlite3.connect((root/"market.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("BEGIN")
        at=matched_cutoff(db,symbol,now)
        raw={}
        for frame,count in targets(symbol).items():
            end=at//FRAMES[frame]*FRAMES[frame]
            rows=[json.loads(x[0]) for x in db.execute(
                "SELECT payload FROM samples WHERE symbol=? AND series=? AND stamp<? ORDER BY stamp DESC LIMIT ?",
                (symbol,"candle:"+frame,end,count))][::-1]
            raw[frame]=(end,count,rows)
    for frame,(end,count,rows) in raw.items():
        # Equal-size fallback only; missing older daily/session history is
        # not manufactured. All feature evaluation still uses original snapshot.
        choices=(count,21) if frame=="1d" else (count,250) if frame=="5m" and count>250 else (count,)
        info={"closed_at":end,"status":"unavailable","requested":count}
        for n in choices:
            try:d=normalize(rows,frame,as_of=at,count=n)
            except ValueError:
                info["demo_error"]="invalid_or_incomplete_window";continue
            try:r=normalize(fetch(symbol,frame,end,n),frame,as_of=at,count=n)
            except Exception as exc:
                info["reference_error"]=type(exc).__name__;continue
            demo[frame]=d;reference[frame]=r
            info.update(status="ready",bars=n,full_window=n==count,
                demo_sha256=hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest(),
                reference_sha256=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest())
            break
        coverage[frame]=info
    report={"version":VERSION,"symbol":symbol,"generated":now,"as_of":at,"completed":int(time.time()),
        "execution_effect":"none","expected_as_of":expected,"cutoff_lag_s":expected-at,"coverage":coverage,
        **compare_reports(scan_windows(symbol,at,demo),scan_windows(symbol,at,reference)),
        "limitations":["Matched candle-only evaluations; no noncandle inputs or full live consensus comparison.",
           "Cutoff uses latest stored closed demo 5m candle, with lag explicitly recorded.",
           "Unmatched and unavailable rule/frame rows excluded from matched votes; neutral may mean no active comparable signal.",
           "Regime weighting uses each source's own candle features.",
           "Reference windows fetched after cutoff, not proof of historic availability. No model requests or order actions."]}
    raw=json.dumps(report,allow_nan=False,separators=(",",":"))
    with closing(sqlite3.connect(root/"reference_strategy.sqlite",timeout=5)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS comparisons(symbol TEXT NOT NULL,generated INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(symbol,generated))")
        db.execute("INSERT OR IGNORE INTO comparisons VALUES(?,?,?)",(symbol,now,raw))
    tmp=root/"reference_strategy.tmp";tmp.write_text(raw+"\n");tmp.replace(root/"reference_strategy.json")
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",required=True);a=p.parse_args()
    failures=0
    for symbol in MARKETS:
        try:
            r=run(a.data_dir,symbol,int(time.time()))
            print(json.dumps({"symbol":symbol,"coverage":{k:v["status"] for k,v in r["coverage"].items()},"comparison_counts":r["comparison_counts"]}),flush=True)
        except Exception as exc:
            failures+=1;print(json.dumps({"symbol":symbol,"error":type(exc).__name__}),flush=True)
    return int(bool(failures))
if __name__=="__main__":raise SystemExit(main())
