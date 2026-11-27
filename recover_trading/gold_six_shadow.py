"""Forward-only XAUTUSD paper comparison, using the demo worker's public market cache."""
import argparse
import json
import math
import sqlite3
import time
from pathlib import Path

SYMBOL = "XAUTUSD"
FEE = 0.0005
SLIP = 0.0002


def new_state(capital):
    return dict(bar=0, quote=0, setup=None, active=False,
                books={k: dict(cash=capital, qty=0, closed=0) for k in ("starter", "six_slot")})


def trade(book, quantity, price, unit, opening):
    # Signed position, quote-currency accounting for a linear contract.
    old = book["qty"]
    if opening:
        book["avg"] = (abs(old) * book.get("avg", 0) + abs(quantity) * price) / abs(old + quantity)
    else:
        book["cash"] += -quantity * unit * (price - book["avg"])
    book["cash"] -= abs(quantity) * unit * price * FEE
    book["qty"] += quantity


def step(state, market, unit, tick, now, log):
    q = market["quotes"].get("ticker")
    if not q or not 0 <= now - q["timestamp_us"]/1e6 <= 90 or q["timestamp_us"] <= state["quote"]:
        return
    bid, ask, mark = q["bid"], q["ask"], q["mark"]
    if not 0 < bid <= ask or not mark > 0:
        return
    state["mark"] = mark
    if state["quote"] and q["timestamp_us"] - state["quote"] > 120_000_000:
        log("quote_gap", dict(previous=state["quote"], current=q["timestamp_us"]))
    state["quote"] = q["timestamp_us"]
    books = state["books"]

    def fill(book, direction, qty, opening, reason):
        px = ask*(1+SLIP) if direction > 0 else bid*(1-SLIP)
        trade(book, direction*qty, px, unit, opening)
        log(reason, dict(book=next(k for k,v in books.items() if v is book),
                         price=px, contracts=qty, remaining=book["qty"], cash=book["cash"]))

    for book in books.values():
        if book["qty"]:
            d = state["side"]
            if d*mark <= d*book["stop"]:
                fill(book, -d, abs(book["qty"]), False, "stop")
                book["closed"] += 1
    frame = market["frames"]["5m"]
    if state["active"] and not any(b["qty"] for b in books.values()):
        state["active"] = False
        state["setup"] = None
        if frame.get("status") == "ready":
            state["bar"] = frame["closed_at"]
        return
    if frame.get("status") != "ready":
        return
    t = frame["closed_at"]
    if t <= state["bar"] or not 0 <= now-t < 300 or q["timestamp_us"] < t*1e6:
        return
    gap = state["bar"] != t-300
    state["bar"] = t
    c = frame["candle"]
    atr = frame["features"].get("atr14")
    if not atr or atr <= 0:
        return
    def prices(d):
        return (c["high"], c["low"], c["close"]) if d==1 else (-c["low"], -c["high"], -c["close"])
    def rounded(x,d):
        return (math.floor(x/tick) if d==1 else math.ceil(x/tick))*tick
    if state["active"]:
        d = state["side"]
        high, low, close = prices(d)
        if c["time"]*1e6 < state["filled_us"]:
            return
        if gap:
            state.update(pivot=[], trigger=None, failed=False)
            log("bar_gap", dict(bar=t))
        state["peak"] = max(state["peak"], high)
        book = books["six_slot"]
        if book["qty"]:
            if state["failed"] and high >= state["level"] and close < state["level"] and not state["reduced"]:
                qty = abs(book["qty"])//2
                if qty:
                    fill(book,-d,qty,False,"failed_reclaim")
                state["reduced"] = True
            state["failed"] = close < state["level"]
            trigger = state["trigger"]
            if trigger is not None and close > trigger and not state["reduced"] and state["slots"] < 6:
                # Use the stop already in force before this bar's trailing update.
                stop_exit = book["stop"]*(1-d*SLIP)
                entry = ask*(1+SLIP) if d==1 else bid*(1-SLIP)
                cash_at_stop = book["cash"] + book["qty"]*unit*(stop_exit-book["avg"]) - abs(book["qty"])*unit*stop_exit*FEE
                cost = unit*(d*(entry-stop_exit)+(entry+stop_exit)*FEE)
                slot = int(state["capital"]*2/(unit*entry))
                qty = min(slot, max(0,int((cash_at_stop-state["floor"])/cost))) if cost>0 else 0
                if qty:
                    fill(book,d,qty,True,"continuation_add")
                    state["slots"] += 1
                    state["last_low"] = state["swing"]
                    state["leg_high"] = high
                    state["pivot"] = []
                state["trigger"] = None
            piv = state["pivot"]
            if len(piv)==2 and piv[0][0]>piv[1][0]<low and piv[1][0]>state["last_low"]:
                state.update(trigger=piv[1][1], swing=piv[1][0])
            state["leg_high"] = max(state["leg_high"],high)
            state["pivot"] = (piv+[[low,state["leg_high"]]])[-2:]
        candidate = rounded(d*(state["peak"]-3*atr),d)
        for b in books.values():
            if b["qty"] and d*b["stop"] < d*candidate < d*mark:
                b["stop"] = candidate
        return

    trend = market["frames"]["15m"]
    if trend.get("status")!="ready" or not 0 <= t-trend["closed_at"] < 900:
        state["setup"] = None
        return
    f = trend["features"]
    if any(f.get(k) is None for k in ("adx14","ema20","ema50")):
        state["setup"] = None
        return
    d = 1 if f["ema20"]>f["ema50"] else -1
    if f["adx14"]<23 or d*(trend["candle"]["close"]-f["ema20"])<=0 or f["ema20"]==f["ema50"]:
        state["setup"] = None
        return
    high,low,close = prices(d)
    setup = state["setup"]
    if gap or (setup and (setup["side"]!=d or t-setup["time"]>1800)):
        setup = state["setup"] = None
    if setup:
        level = setup["level"]
        if close < level:
            state["setup"] = None
        elif low<=level<close:
            entry = ask*(1+SLIP) if d==1 else bid*(1-SLIP)
            stop = rounded(entry-d*1.5*atr,d)
            if stop<=0 or d*(mark-stop)<=0:
                state["setup"]=None
                return
            quantities = [int(b["cash"]*2/(unit*entry)) for b in books.values()]
            if min(quantities)<=0:
                state["setup"]=None
                return
            capital = books["six_slot"]["cash"]
            for b,qty in zip(books.values(),quantities):
                b["stop"] = stop
                fill(b,d,qty,True,"starter_fill")
            b=books["six_slot"]
            exit_px=stop*(1-d*SLIP)
            state.update(active=True,setup=None,side=d,level=level,capital=capital,
                         floor=b["cash"]+b["qty"]*unit*(exit_px-entry)-abs(b["qty"])*unit*exit_px*FEE,
                         filled_us=q["timestamp_us"],slots=1,peak=d*entry,leg_high=d*entry,
                         last_low=level,pivot=[],trigger=None,reduced=False,failed=False)
        return
    key = "prior_high20" if d==1 else "prior_low20"
    level = frame["features"].get(key)
    if level is not None and close>d*level:
        state["setup"] = dict(time=t,side=d,level=d*level)
        log("breakout", state["setup"])


def main():
    from tradebot.feature_snapshot_v3 import snapshot
    from recover_trading.broker import DeltaDemo
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market",type=Path)
    parser.add_argument("ledger",type=Path)
    args=parser.parse_args()
    if args.market.resolve()==args.ledger.resolve() or not args.market.is_file():
        parser.error("supply the existing Gold market cache and a separate shadow ledger")
    spec=DeltaDemo().product(SYMBOL)
    if spec["symbol"]!=SYMBOL or spec["contract_unit_currency"]!="XAUT" or spec["settling_asset"]["symbol"]!="USD":
        raise ValueError("unexpected contract")
    unit,tick=float(spec["contract_value"]),float(spec["tick_size"])
    if min(unit,tick)<=0:
        raise ValueError("invalid contract dimensions")
    db=sqlite3.connect(args.ledger)
    db.execute("CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS events(stamp INTEGER, kind TEXT, details TEXT)")
    while True:
        now=int(time.time())
        market=snapshot(args.market,now,symbols=(SYMBOL,))["markets"][SYMBOL]
        with db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()
            state=json.loads(row[0]) if row else new_state(10000)
            def log(kind,details):
                db.execute("INSERT INTO events VALUES(?,?,?)",(now,kind,json.dumps(details)))
            step(state,market,unit,tick,now,log)
            db.execute("INSERT OR REPLACE INTO checkpoint VALUES(1,?)",(json.dumps(state),))
        if now//60 != (now-15)//60:
            print(json.dumps(dict(symbol=SYMBOL,last_quote_us=state["quote"],last_bar=state["bar"],books=state["books"])),flush=True)
        time.sleep(15)


if __name__=="__main__":
    main()
