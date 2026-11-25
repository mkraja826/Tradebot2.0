"""Independent, public-reference indicator comparisons; no execution integration."""
import argparse,json,math,sqlite3,time
from pathlib import Path
from contextlib import closing
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
from tradebot.indicators_v3 import features
from tradebot.advanced_indicators_v3 import advanced_technicals
from .reference_history import candles
from .price_audit import audit

VERSION="dual-market-v1"
FRAMES_USED=("5m","15m","1h","4h")
COUNT=250
INDICATORS=("ema20","ema50","ema200","rsi14","adx14","atr14_pct","macd_histogram","supertrend_direction","rolling_vwap20","confirmed_swing_high","confirmed_swing_low")

def finite(x):
    return x if type(x) in (int,float) and math.isfinite(x) else None

def sign(x):
    return "UP" if x>0 else "DOWN" if x<0 else "NEUTRAL"

def states(f):
    a,b=finite(f.get("ema50")),finite(f.get("ema200"))
    macd=finite(f.get("macd_histogram"));rsi=finite(f.get("rsi14"));st=finite(f.get("supertrend_direction"))
    return {"ema50_vs_200":sign(a-b) if a is not None and b is not None else None,
        "macd_histogram":sign(macd) if macd is not None else None,
        "rsi_vs_50":sign(rsi-50) if rsi is not None else None,
        "supertrend":sign(st) if st in (-1,1) else None}

def compare(symbol,frame,end,demo,reference):
    demo=normalize(demo,frame,as_of=end,count=COUNT)
    reference=normalize(reference,frame,as_of=end,count=COUNT)
    def get(bars):
        f=features(bars,symbol,frame,as_of=end)["features"]
        f.update(advanced_technicals(bars))
        return f
    d,r=get(demo),get(reference)
    ds,rs=states(d),states(r)
    signals={k:{"demo":v,"reference":rs[k],"agree":v==rs[k] if v is not None and rs[k] is not None else None} for k,v in ds.items()}
    close_demo,close_ref=demo[-1]["close"],reference[-1]["close"]
    return {"status":"ready","closed_at":end,"bars_per_source":COUNT,
        "demo_close":close_demo,"reference_close":close_ref,
        "signed_close_difference_bps":(close_demo/close_ref-1)*10000,
        "indicators":{k:{"demo":finite(d.get(k)),"reference":finite(r.get(k))} for k in INDICATORS},
        "directional_checks":signals,
        "agreement_count":sum(x["agree"] is True for x in signals.values()),
        "comparable_count":sum(x["agree"] is not None for x in signals.values())}

def run(root,symbol,now,fetch=candles):
    if symbol not in MARKETS or type(now) is not int:raise ValueError("invalid market")
    root=Path(root)/symbol
    frames={}
    with closing(sqlite3.connect((root/"market.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("BEGIN")
        windows={}
        for frame in FRAMES_USED:
            step=FRAMES[frame];expected=now//step*step
            bars=[json.loads(x[0]) for x in db.execute(
                "SELECT payload FROM samples WHERE symbol=? AND series=? AND stamp<? ORDER BY stamp DESC LIMIT ?",
                (symbol,"candle:"+frame,expected,COUNT))][::-1]
            if not bars:
                frames[frame]={"status":"demo_unavailable","expected_closed_at":expected};continue
            end=bars[-1]["time"]+step
            try:bars=normalize(bars,frame,as_of=end,count=COUNT)
            except ValueError:
                frames[frame]={"status":"demo_invalid_window","expected_closed_at":expected};continue
            windows[frame]=(end,expected,bars)
    # Close the database read transaction before network I/O.
    for frame,(end,expected,bars) in windows.items():
        try:
            ref=fetch(symbol,frame,end,COUNT)
            row=compare(symbol,frame,end,bars,ref)
            if frame=="5m":
                row["quality"]={name:{k:audit(source)[k] for k in ("rows","gap_count","range_count")} for name,source in (("demo",bars),("reference",ref))}
        except Exception as exc:
            row={"status":"reference_unavailable_or_invalid","error":type(exc).__name__,"closed_at":end}
        row.update(expected_closed_at=expected,lag_s=expected-end)
        frames[frame]=row
    result={"version":VERSION,"symbol":symbol,"generated":now,"completed":int(time.time()),
        "mode":"observation_only","execution_effect":"none","frames":frames,
        "limitations":["Independent candle-only indicator checks, not full strategy consensus.",
          "Same 250 completed bars and aligned UTC boundaries per source.",
          "A stale demo window remains labeled stale; reference prices are not execution prices.",
          "Indicator agreement does not establish predictive edge. No AI or order requests."]}
    # Dedicated append-only observation journal with one record per scheduled run.
    raw=json.dumps(result,allow_nan=False,separators=(",",":"))
    with closing(sqlite3.connect(root/"dual_market.sqlite",timeout=5)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS comparisons (symbol TEXT NOT NULL, generated INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(symbol,generated))")
        db.execute("INSERT OR IGNORE INTO comparisons VALUES(?,?,?)",(symbol,now,raw))
    tmp=root/"dual_market.tmp";tmp.write_text(raw+"\n");tmp.replace(root/"dual_market.json")
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",required=True);a=p.parse_args()
    failures=0
    for symbol in MARKETS:
        try:
            r=run(a.data_dir,symbol,int(time.time()))
            print(json.dumps({"symbol":symbol,"frames":{k:v["status"] for k,v in r["frames"].items()}}),flush=True)
        except Exception as exc:
            failures+=1;print(json.dumps({"symbol":symbol,"error":type(exc).__name__}),flush=True)
    return int(bool(failures))
if __name__=="__main__":raise SystemExit(main())
