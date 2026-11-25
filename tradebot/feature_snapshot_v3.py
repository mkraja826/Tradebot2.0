"""Build the research-only feature snapshot from a consistent SQLite read."""
import json,sqlite3
from contextlib import closing
from pathlib import Path
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
from tradebot.indicators_v3 import features
from tradebot.advanced_indicators_v3 import advanced_technicals,daily_pivots
from tradebot.session_context_v3 import session_features,ticker_changes
from tradebot.gold_context_v3 import gold_context

def snapshot(database,as_of,*,symbols=MARKETS,candle_as_of=None):
    if type(as_of) is not int or as_of<=0: raise ValueError("invalid_as_of")
    if not symbols or any(x not in MARKETS for x in symbols) or len(set(symbols))!=len(symbols): raise ValueError("invalid_symbols")
    observed_as_of=as_of
    if candle_as_of is not None:
        if type(candle_as_of) is not int or not 0<candle_as_of<=as_of: raise ValueError("invalid_candle_as_of")
        as_of=candle_as_of
    uri=Path(database).resolve().as_uri()+"?mode=ro"
    with closing(sqlite3.connect(uri,uri=True)) as db:
        db.execute("BEGIN")
        def history(symbol,series,cutoff,limit):
            return [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM samples WHERE symbol=? AND series=? AND stamp<? ORDER BY stamp DESC LIMIT ?",
                (symbol,series,cutoff,limit)).fetchall()][::-1]
        result={}
        for symbol in symbols:
            frames={}
            for frame,step in FRAMES.items():
                count=180 if symbol=="XAUTUSD" and frame=="1d" else 250
                bars=history(symbol,"candle:"+frame,as_of//step*step,count)
                try:
                    rows=normalize(bars,frame,as_of=as_of,count=count)
                    item=features(rows,symbol,frame,as_of=as_of)
                    item["features"].update(advanced_technicals(rows))
                    item["unavailable"]=sorted(k for k,v in item["features"].items() if v is None)
                    item["candle"]=rows[-1]
                    item["previous_candle"]=rows[-2]
                    item["previous_inside"]=int(rows[-2]["high"]<rows[-3]["high"] and rows[-2]["low"]>rows[-3]["low"])
                    item["previous_features"]=features(rows[:-1],symbol,frame,as_of=as_of-step)["features"]
                    item["previous_features"].update(advanced_technicals(rows[:-1]))
                    item["prior_20_all_weekend"]=all((r["time"]//86400+3)%7>=5 for r in rows[-21:])
                    item["status"]="ready"
                    frames[frame]=item
                except ValueError as e: frames[frame]={"status":"unavailable","reason":str(e)}
            context=session_features(history(symbol,"candle:5m",as_of//300*300,600),as_of=as_of)
            context.update(ticker_changes(history(symbol,"ticker",observed_as_of*1_000_000+1,180),as_of=observed_as_of))
            daily=history(symbol,"candle:1d",as_of//86400*86400,1)
            try:
                row=normalize(daily,"1d",as_of=as_of,count=1)[0]
                context.update({"previous_day_"+k:v for k,v in daily_pivots(row).items()})
                context.update(previous_day_high=row["high"],previous_day_low=row["low"],previous_day_close=row["close"])
            except ValueError:
                for k in ("pivot","r1","s1","r2","s2","high","low","close"): context["previous_day_"+k]=None
            if symbol=="XAUTUSD":
                session_bars=history(symbol,"candle:5m",as_of//300*300,900)
                daily_bars=history(symbol,"candle:1d",as_of//86400*86400,21)
                for frame in ("5m","15m","1h","4h"):
                    item=frames[frame]
                    if item["status"]=="ready":
                        item["gold_context"]=gold_context(session_bars,daily_bars,closed_at=item["closed_at"],frame=frame)
            if symbol=="BTCUSD":
                from tradebot.derivative_context_v3 import features as derivative_features
                context.update(derivative_features(history(symbol,"funding:1h",as_of//3600*3600,74),history(symbol,"mark:5m",as_of//300*300,2),history(symbol,"index:5m",as_of//300*300,2),as_of=as_of))
            quotes={}
            for kind in ("ticker","book","flow",*(("xau_reference",) if symbol=="XAUTUSD" else ())):
                latest=history(symbol,kind,observed_as_of*1_000_000+1,1)
                quotes[kind]=latest[0] if latest and 0<=observed_as_of*1_000_000-latest[0]["timestamp_us"]<=120_000_000 else None
            if symbol=="XAUTUSD":
                from tradebot.gold_reference_v3 import features as reference_features
                context.update(reference_features(quotes,as_of=observed_as_of))
            result[symbol]={"frames":frames,"context":context,"quotes":quotes}
        return {"mode":"read_only_research","as_of":observed_as_of,"candle_as_of":as_of,"markets":result}
