"""Pure point-in-time 5m BTC technical indicators from completed OHLCV bars.

Uses only the 288 validated original Delta DEMO 5m bars. No exchange API,
AI service, file writes or order authority. Missing volume means missing RVOL.
"""
from math import isfinite, sqrt

PERIOD = 14


def _ema_series(values, span):
    if len(values) < span:
        return []
    ema = sum(values[:span]) / span
    out = [ema]
    weight = 2 / (span + 1)
    for value in values[span:]:
        ema += (value - ema) * weight
        out.append(ema)
    return out


def _wilder_rsi(closes):
    changes = [b-a for a,b in zip(closes,closes[1:])]
    if len(changes) < PERIOD:
        return None
    avg_up = sum(max(0, v) for v in changes[:PERIOD])/PERIOD
    avg_down = sum(max(0, -v) for v in changes[:PERIOD])/PERIOD
    for change in changes[PERIOD:]:
        avg_up += (max(change, 0)-avg_up)/PERIOD
        avg_down += (max(-change, 0)-avg_down)/PERIOD
    if avg_down == 0:
        return 50.0 if avg_up == 0 else 100.0
    if avg_up == 0:
        return 0.0
    return 100 - 100/(1 + avg_up/avg_down)


def _wilder_adx(highs, lows, closes):
    if len(closes) < PERIOD*2:
        return None
    triples = []
    for i in range(1,len(closes)):
        up = highs[i]-highs[i-1]
        down = lows[i-1]-lows[i]
        plus = up if up>down and up>0 else 0.0
        minus = down if down>up and down>0 else 0.0
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        triples.append((tr,plus,minus))
    tr_sum=sum(t[0] for t in triples[:PERIOD])
    plus_sum=sum(t[1] for t in triples[:PERIOD])
    minus_sum=sum(t[2] for t in triples[:PERIOD])
    dx=[]
    positive=negative=0.0
    for i in range(PERIOD-1,len(triples)):
        if i>=PERIOD:
            tr,plus,minus=triples[i]
            tr_sum=tr_sum - tr_sum/PERIOD + tr
            plus_sum=plus_sum - plus_sum/PERIOD + plus
            minus_sum=minus_sum - minus_sum/PERIOD + minus
        positive=100*plus_sum/tr_sum if tr_sum>0 else 0.0
        negative=100*minus_sum/tr_sum if tr_sum>0 else 0.0
        denom=positive+negative
        dx.append(100*abs(positive-negative)/denom if denom else 0.0)
    if len(dx)<PERIOD:
        return None
    adx=sum(dx[:PERIOD])/PERIOD
    for value in dx[PERIOD:]:
        adx+=(value-adx)/PERIOD
    return {"adx14":round(adx,3),"plus_di14":round(positive,3),
            "minus_di14":round(negative,3)}


def _macd(closes):
    fast=_ema_series(closes,12)
    slow=_ema_series(closes,26)
    if not slow:
        return None
    # Both lists terminate at same current bar.
    macd=[a-b for a,b in zip(fast[-len(slow):],slow)]
    signal=_ema_series(macd,9)
    if not signal:
        return None
    return {"line":round(macd[-1],6),"signal":round(signal[-1],6),
            "histogram":round(macd[-1]-signal[-1],6)}


def compute_technical_5m(candles):
    """OHLCV rows are completed ordered bars; reject any invalid candle."""
    if not isinstance(candles,(list,tuple)) or len(candles)<35:
        raise ValueError("btc_technical_history_incomplete")
    hs=[];ls=[];cs=[];vs=[]
    previous=None
    for bar in candles:
        if not isinstance(bar,dict):
            raise ValueError("btc_technical_invalid_bar")
        try:
            values=(float(bar[k]) for k in ("open","high","low","close","volume"))
            o,h,l,c,v=tuple(values)
        except (ValueError,TypeError,KeyError,OverflowError):
            raise ValueError("btc_technical_invalid_bar") from None
        if not all(map(isfinite,(o,h,l,c,v))) or not (0<l<=min(o,c)<=max(o,c)<=h) or v<0:
            raise ValueError("btc_technical_invalid_bar")
        if "time" in bar:
            t=bar["time"]
            if type(t) is not int or (previous is not None and t!=previous+300):
                raise ValueError("btc_technical_nonconsecutive_bars")
            previous=t
        hs.append(h);ls.append(l);cs.append(c);vs.append(v)
    rsi=_wilder_rsi(cs)
    adx=_wilder_adx(hs,ls,cs)
    macd=_macd(cs)
    subset=cs[-20:]
    middle=sum(subset)/20
    sigma=sqrt(sum((value-middle)**2 for value in subset)/20)
    upper=middle+2*sigma
    lower=middle-2*sigma
    reference=sum(vs[-21:-1])/20 if len(vs)>=21 else 0
    rvol=round(vs[-1]/reference,3) if reference>0 else None
    return {
        "source":"completed_5m_local_candles_only",
        "bars_used":len(cs),
        "rsi14":round(rsi,3) if rsi is not None else None,
        "adx14":adx,
        "relative_volume20": {
            "ratio":rvol,"current_volume":round(vs[-1],6),
            "previous_20_mean_volume":round(reference,6),
            "status":"available" if rvol is not None else "unavailable_zero_baseline"},
        "macd_12_26_9":macd,
        "bollinger_20_2": {
            "middle":round(middle,6),
            "upper":round(upper,6),
            "lower":round(lower,6),
            "bandwidth_bps":round((upper-lower)/middle*10000,3),
            "percent_b":round((cs[-1]-lower)/(upper-lower),6) if upper>lower else None},
        "trade_authorized":False,
    }
