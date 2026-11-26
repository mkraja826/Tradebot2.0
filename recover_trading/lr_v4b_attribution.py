"""LR-V4-B durable strategy ownership and management proposals, no broker calls."""
import hashlib
import json
import sqlite3
from .lr_v4b import bracket, trail, HOLD_MINUTES
from .performance import dec


class Attribution:
    def __init__(self, db):
        self.db = db
        with db:
            db.execute("""CREATE TABLE IF NOT EXISTS lr_v4b_entries (
                signal_id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL,
                signal_time INTEGER NOT NULL, side TEXT NOT NULL,
                structural_stop REAL NOT NULL, state TEXT NOT NULL,
                detail TEXT NOT NULL)""")

    def reserve(self, signal, now):
        """Reserve a current confirmed BTC signal once, before any submission."""
        if signal.get("version") != "lr-v4b" or signal.get("symbol") != "BTCUSD":
            raise ValueError("wrong strategy or market")
        t, burst = signal["signal_time"], signal["burst_time"]
        side = signal["side"]
        stop = dec(signal["initial_stop"])
        if (type(t) is not int or type(burst) is not int or t % 60 or burst % 60
                or not 0 <= now-t < 60 or not 0 <= t-burst <= 300
                or side not in ("buy", "sell") or stop is None or stop <= 0):
            raise ValueError("invalid or stale signal")
        ident = hashlib.sha256(f"lr-v4b:BTCUSD:{burst}:{t}:{side}".encode()).hexdigest()
        cid = hashlib.sha256(("recover:"+ident).encode()).hexdigest()[:32]
        try:
            with self.db:
                self.db.execute("INSERT INTO lr_v4b_entries VALUES(?,?,?,?,?,'reserved',?)",
                                (ident,cid,t,side,float(stop),json.dumps(signal,allow_nan=False)))
        except sqlite3.IntegrityError:
            return None
        return {"decision_id":ident,"client_id":cid}

    def ownership(self, lineage, position):
        """Only receipt-linked, single flat-to-open entry lineage is accepted.

        Caller must provide lineage verified against complete fresh broker fills,
        and must not infer lineage from the current position alone.
        """
        if not isinstance(lineage,dict) or not isinstance(position,dict):
            return None
        oid = lineage.get("entry_order")
        if oid is None or not position.get("created_at"):
            return None
        matches = []
        for cid, side, structural_stop, raw in self.db.execute(
            """SELECT l.client_id,l.side,l.structural_stop,o.detail
               FROM lr_v4b_entries l JOIN orders o ON o.client_id=l.client_id
               WHERE o.symbol='BTCUSD' AND o.status='acknowledged'"""):
            try:
                receipt = json.loads(raw)
                if str(receipt.get("id")) != str(oid) or receipt.get("client_order_id") != cid:
                    continue
                q = dec(position.get("size"))
                if (q is None or q == 0 or (q>0)!=(side=="buy")
                        or q != dec(lineage["size"])
                        or dec(position.get("entry_price")) != dec(lineage["entry_price"])
                        or str(position.get("product_id")) != str(receipt.get("product_id"))):
                    continue
                b = bracket(side,lineage["entry_price"],structural_stop)
                matches.append({**b,"client_id":cid,"entry_order":str(oid),"side":side,
                                "position_created_at":position["created_at"]})
            except (ValueError,TypeError,KeyError,ArithmeticError):
                continue
        return matches[0] if len(matches)==1 else None


def management_proposal(owner, current_stop, candles, ema_values, *, fill_time, now, activated=False):
    """Calculate a proposal on complete post-fill bars only; no broker effects.

    A candle containing the fill is excluded because its pre-fill extremes
    cannot establish favourable post-fill movement.
    """
    if len(candles)!=len(ema_values):
        raise ValueError("EMA alignment")
    if not owner or type(fill_time) is not int or not 0 <= now-fill_time:
        raise ValueError("invalid fill time or owner")
    if now-fill_time >= HOLD_MINUTES*60:
        return {"action":"close_at_timeout","execution_effect":"none"}
    stop=current_stop
    last=None
    expected=((fill_time+59)//60)*60
    for candle, ema in zip(candles,ema_values):
        t=candle["time"]
        if type(t) is not int or t%60 or (last is not None and t!=last+60):
            raise ValueError("invalid candle chronology")
        last=t
        if t < expected:
            continue
        if t != expected or t+60>now:
            raise ValueError("missing or unclosed post-fill candle")
        expected+=60
        r=trail(owner["side"],owner["entry"],owner["initial_stop"],stop,candle,ema,activated)
        stop,activated=r["proposed_stop"],r["activated"]
    if expected < now//60*60:
        raise ValueError("post-fill candle history incomplete")
    return {"action":"amend_stop" if stop!=current_stop else "maintain",
            "activated":activated,"stop":stop,"target":owner["target"],"execution_effect":"none"}
