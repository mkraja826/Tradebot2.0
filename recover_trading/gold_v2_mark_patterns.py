"""Additional mark-only entry hypotheses. All inputs are completed candles."""
from .gold_v2_technical import momentum

def patterns(bars,technical,*,higher,mid,atr):
    if len(bars)<22 or atr<=0:return []
    last,prior=bars[-1],bars[-2]
    hi=max(b.h for b in bars[-22:-2]);lo=min(b.l for b in bars[-22:-2])
    adx=technical.get("adx");rsi=technical.get("rsi14")
    previous_rsi=momentum(bars[:-1])
    found=[]
    for side in (1,-1):
        aligned=higher==mid==side
        level=hi if side==1 else lo
        extreme=last.l if side==1 else last.h
        # Prior close must break the earlier range, then retest and hold.
        if aligned and side*(prior.c-level)>.15*atr and abs(extreme-level)<=.25*atr and side*(last.c-level)>.1*atr:
            found.append(("mark_breakout_retest",side))
        # Mark-price range rejection, not evidence of actual liquidations.
        boundary=lo if side==1 else hi
        if side*(extreme-boundary)<-.1*atr and side*(last.c-boundary)>.1*atr and side*(last.c-last.o)>.1*atr:
            found.append(("mark_range_rejection",side))
        # RSI recovery in a low-directional-strength regime.
        if adx is not None and adx<20 and rsi is not None and previous_rsi is not None:
            if (side==1 and previous_rsi<=30<rsi) or (side==-1 and previous_rsi>=70>rsi):
                found.append(("mark_rsi_reversal",side))
        # DI trend continuation, confirmed close through a previously identified swing.
        di=technical.get("plus_di" if side==1 else "minus_di")
        opposite=technical.get("minus_di" if side==1 else "plus_di")
        swing=technical.get("last_swing_high" if side==1 else "last_swing_low")
        structure="higher_highs_lows" if side==1 else "lower_highs_lows"
        if aligned and adx is not None and adx>=25 and di is not None and opposite is not None and di>opposite and technical.get("structure")==structure and swing is not None:
            if side*(prior.c-swing)<=0 and side*(last.c-swing)>.1*atr:
                found.append(("mark_swing_continuation",side))
    return found
