"""Pure, read-only 1-of-10 indicator signals. No AI, API or order authority."""
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite, sqrt
from tradebot.btc_technical_indicators import _ema_series, _wilder_rsi, _wilder_adx, _macd

STRATEGIES = (
    "ema_trend_continuation", "ema_rsi_stoch_pullback",
    "macd_adx_volume", "donchian_breakout", "breakout_retest",
    "bollinger_squeeze", "bollinger_mean_reversion",
    "vwap_reclaim", "support_resistance_bounce", "liquidity_sweep_reversal",
)
MARKETS = frozenset(("BTCUSD", "XAUTUSD"))
MIN_BARS = 220


def _stoch(highs, lows, closes):
    lo, hi = min(lows[-14:]), max(highs[-14:])
    return 50.0 if lo == hi else 100 * (closes[-1]-lo)/(hi-lo)


def _bands(closes):
    window = closes[-20:]
    avg = sum(window)/20
    sigma = sqrt(sum((x-avg)**2 for x in window)/20)
    return avg-2*sigma, avg, avg+2*sigma, 4*sigma/avg


def _vwap(rows, candle_time):
    window = [r for r in rows if r[0]//86400 == candle_time//86400]
    vol = sum(r[5] for r in window)
    return (sum((r[2]+r[3]+r[4])/3*r[5] for r in window)/vol
            if len(window) >= 6 and vol > 0 else None)


def _features(candles, symbol, as_of):
    if symbol not in MARKETS:
        raise ValueError("isolated_market_required")
    if type(as_of) is not int:
        raise ValueError("integer_as_of_required")
    if not isinstance(candles, (list, tuple)) or len(candles) < MIN_BARS:
        raise ValueError("insufficient_completed_candles")
    rows = []
    for bar in candles:
        if type(bar) is not dict or type(bar.get("time")) is not int:
            raise ValueError("invalid_candle")
        t = bar["time"]
        try:
            o, h, l, c, v = (float(bar[k]) for k in ("open","high","low","close","volume"))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("invalid_candle") from None
        if (t%300 or not all(isfinite(n) for n in (o,h,l,c,v))
                or not (0 < l <= min(o,c) <= max(o,c) <= h) or v < 0
                or (rows and t != rows[-1][0]+300)):
            raise ValueError("invalid_or_nonconsecutive_candle")
        rows.append((t,o,h,l,c,v))
    stamp = rows[-1][0]
    if stamp+300 > as_of:
        raise ValueError("current_candle_not_closed")
    if as_of-(stamp+300) >= 900:
        raise ValueError("candles_stale")
    opens=[r[1] for r in rows]
    highs=[r[2] for r in rows]
    lows=[r[3] for r in rows]
    closes=[r[4] for r in rows]
    vols=[r[5] for r in rows]
    ema=lambda x,n:_ema_series(x,n)[-1]
    adx=_wilder_adx(highs,lows,closes)
    bb=_bands(closes)
    previous_bb=_bands(closes[:-1])
    prev_volume=sum(vols[-21:-1])/20
    ranges=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),
                abs(lows[i]-closes[i-1]))
            for i in range(len(closes)-14,len(closes))]
    return {
        "symbol":symbol,"time":stamp,"open":opens[-1],
        "close":closes[-1],"prev_close":closes[-2],
        "high":highs[-1],"low":lows[-1],
        "prev_high":highs[-2],"prev_low":lows[-2],
        "ema20":ema(closes,20),"ema20_prev":ema(closes[:-1],20),
        "ema50":ema(closes,50),"ema200":ema(closes,200),
        "rsi":_wilder_rsi(closes),"rsi_prev":_wilder_rsi(closes[:-1]),
        "adx":adx["adx14"],"plus_di":adx["plus_di14"],
        "minus_di":adx["minus_di14"],
        "macd":_macd(closes)["histogram"],
        "prev_macd":_macd(closes[:-1])["histogram"],
        "stoch":_stoch(highs,lows,closes),
        "prev_stoch":_stoch(highs[:-1],lows[:-1],closes[:-1]),
        "rvol":vols[-1]/prev_volume if prev_volume>0 else None,
        "atr":sum(ranges)/len(ranges),
        "bb_low":bb[0],"bb_mid":bb[1],"bb_high":bb[2],"bb_width":bb[3],
        "prev_bb_low":previous_bb[0],"prev_bb_high":previous_bb[2],
        "prev_bb_width":previous_bb[3],
        "vwap":_vwap(rows,stamp),"prev_vwap":_vwap(rows[:-1],stamp),
        "range_high":max(highs[-21:-1]),"range_low":min(lows[-21:-1]),
        "retest_high":max(highs[-22:-2]),"retest_low":min(lows[-22:-2]),
        "true_range":ranges[-1],
    }


def _evaluate(f):
    """Ten independent detectors. Any one signal is sufficient for AI evaluation."""
    found=[]
    c,p,o=f["close"],f["prev_close"],f["open"]
    e20,e50,e200=f["ema20"],f["ema50"],f["ema200"]
    rsi,rprev=f["rsi"],f["rsi_prev"]
    adx,vol=f["adx"],f["rvol"]
    for side,sign in (("LONG",1),("SHORT",-1)):
        good=lambda a,b:sign*(a-b)>0
        rdir=rsi if sign==1 else 100-rsi
        sdir=f["stoch"] if sign==1 else 100-f["stoch"]
        trend=good(e20,e50) and good(e50,e200)
        di=good(f["plus_di"],f["minus_di"])
        advance=good(rsi,rprev)
        candle=good(c,o)
        level=f["range_high"] if sign==1 else f["range_low"]
        reversal_level=f["range_low"] if sign==1 else f["range_high"]
        retest=f["retest_high"] if sign==1 else f["retest_low"]
        extreme=f["low"] if sign==1 else f["high"]
        prev_extreme=f["prev_low"] if sign==1 else f["prev_high"]
        inner_band=f["bb_low"] if sign==1 else f["bb_high"]
        prev_band=f["prev_bb_low"] if sign==1 else f["prev_bb_high"]
        outer_band=f["bb_high"] if sign==1 else f["bb_low"]
        wick=(min(c,o)-f["low"]) if sign==1 else (f["high"]-max(c,o))
        body=max(abs(c-o),c*1e-7)
        def emit(index, qualifies, bonuses=()):
            if not qualifies:
                return
            strength=min(95,65+5*sum(bool(x) for x in bonuses))
            strategy=STRATEGIES[index]
            identifier=f'{f["symbol"]}:{f["time"]}:{strategy}:{side}'
            found.append({
                "strategy_id":strategy,"direction":side,
                "score":strength,"strength":"strong" if strength>=80 else "moderate",
                "signal_id":sha256(identifier.encode()).hexdigest()[:20],
                "candle_time":f["time"],"trade_authorized":False,
            })

        emit(0,trend and di and adx>=22 and 52<=rdir<=75
             and good(c,e20) and candle,
             (adx>=28,advance,vol is not None and vol>=1.15))
        touched=(prev_extreme<=f["ema20_prev"] if sign==1
                 else prev_extreme>=f["ema20_prev"])
        emit(1,good(e20,e50) and touched and good(c,e20)
             and candle and advance and 42<=rdir<=70 and 30<=sdir<=75
             and good(f["stoch"],f["prev_stoch"]),
             (di,adx>=20,vol is not None and vol>=1.1))
        emit(2,good(f["macd"],0) and not good(f["prev_macd"],0)
             and di and adx>=18 and vol is not None and vol>=1.2,
             (adx>=25,vol is not None and vol>=1.5,good(e20,e50)))
        emit(3,good(c,level) and candle and f["true_range"]>=.9*f["atr"]
             and vol is not None and vol>=1.2,
             (adx>=20,di,vol is not None and vol>=1.5))
        retested=extreme<=retest if sign==1 else extreme>=retest
        emit(4,good(p,retest) and retested and good(c,retest)
             and candle and good(e20,e50) and vol is not None and vol>=.9,
             (di,adx>=20,vol is not None and vol>=1.3))
        emit(5,f["prev_bb_width"]<=.035
             and f["bb_width"]>1.08*f["prev_bb_width"]
             and good(c,outer_band) and candle
             and vol is not None and vol>=1.15,
             (f["true_range"]>=f["atr"],di,vol is not None and vol>=1.4))
        prior_outside=p<prev_band if sign==1 else p>prev_band
        emit(6,adx<=18 and prior_outside and good(c,inner_band)
             and candle and advance and rdir<=55,
             (good(c,p),rdir>=35,vol is not None and vol>=.8))
        vw,pvw=f["vwap"],f["prev_vwap"]
        emit(7,vw is not None and pvw is not None
             and not good(p,pvw) and good(c,vw) and good(e20,e50)
             and rdir>=50,
             (di,adx>=20,vol is not None and vol>=1.2))
        near=extreme<=reversal_level*1.002 if sign==1 else extreme>=reversal_level*.998
        emit(8,near and candle and wick>=1.3*body
             and good(f["stoch"],f["prev_stoch"]) and sdir<=50,
             (advance,f["true_range"]>=.7*f["atr"],di))
        swept=extreme<reversal_level if sign==1 else extreme>reversal_level
        emit(9,swept and good(c,reversal_level) and wick>=body
             and advance and candle,
             (sdir<=55,f["true_range"]>=f["atr"],
              vol is not None and vol>=1.1))
    return sorted(found,key=lambda x:(-x["score"],x["strategy_id"],x["direction"]))


def scan_completed_5m(candles, symbol, *, as_of=None):
    """Completed candles in; read-only AI trigger out. Never execute an order."""
    when=int(datetime.now(timezone.utc).timestamp()) if as_of is None else as_of
    f=_features(candles,symbol,when)
    signals=_evaluate(f)
    sides={signal["direction"] for signal in signals}
    return {
        "symbol":symbol,"candle_time":f["time"],"trigger_ai":bool(signals),
        "signals":signals,"candidate_count":len(signals),
        "conflicting_directions":len(sides)>1,
        "direction_hint":next(iter(sides)) if len(sides)==1 else None,
        "score_type":"uncalibrated_heuristic",
        "execution_authorized":False,
        "source":"completed_5m_local_1_of_10",
    }

