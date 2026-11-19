"""Read-only chart data and per-market FIRE replay."""
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import json
import math
import sqlite3
from threading import Lock
import time

from tradebot.fire_market import SYMBOLS

PERIODS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def epoch(value):
    try:
        number = float(value)
        if number > 1e14:
            number /= 1e6
        elif number > 1e11:
            number /= 1000
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value).timestamp()
        except (TypeError, ValueError):
            return None


class ChartDesk:
    def __init__(self, exchange, stores):
        self.archive = None
        self.exchange = exchange
        self.stores = stores
        self.cache = {}
        self.lock = Lock()

    def cached(self, key, ttl, loader):
        with self.lock:
            hit = self.cache.get(key)
            if hit and time.monotonic() < hit[0]:
                return hit[1]
        result = loader()
        with self.lock:
            if len(self.cache) >= 128:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (time.monotonic() + ttl, result)
        return result

    def trades(self, symbol, page=0):
        with closing(self.stores[symbol]._connect()) as db:
            rows = db.execute("SELECT press,created_at,updated_at,status,result FROM fire_requests "
                              "ORDER BY created_at DESC LIMIT 40 OFFSET ?", (40*page,)).fetchall()
        return [dict(json.loads(raw), id=key, at=epoch(at), updated=epoch(updated), status=status)
                for key, at, updated, status, raw in rows]

    def account(self, symbol, ticker):
        pid = ticker["product_id"]
        raw = self.exchange._request("GET", "/v2/positions", params={"product_id": pid}, auth=True)["result"]
        rows = [raw] if isinstance(raw, dict) else raw
        positions = []
        for row in rows:
            if str(row.get("product_id", pid) if isinstance(raw, dict) else row["product_id"]) != str(pid):
                raise ValueError("Mismatched position")
            if Decimal(str(row["size"])):
                positions.append({k: row.get(k) for k in ("size","entry_price","unrealized_pnl")})
        orders = self.cached("orders", 4, self.exchange.open_orders)
        exits = [{"kind": o["stop_order_type"], "price": o["stop_price"], "side": o.get("side")}
                 for o in orders if str(o["product_id"]) == str(pid) and o.get("state") in ("open","pending")
                 and o.get("bracket_order") is True and o.get("stop_price")
                 and o.get("stop_order_type") in ("stop_loss_order","take_profit_order")]
        return {"positions": positions, "exits": exits}

    def read(self, query):
        symbol = query.get("symbol", ["BTCUSD"])[0]
        period = query.get("period", ["5m"])[0]
        if symbol not in SYMBOLS or period not in PERIODS:
            raise ValueError("Unsupported chart")
        step = PERIODS[period]
        now = int(time.time())
        summary = query.get("summary") == ["1"]
        page = int(query.get("page", ["0"])[0])
        if not 0 <= page <= 1000000:
            raise ValueError("Invalid history page")
        trades = [] if summary else self.trades(symbol, page)
        trade_id = query.get("trade", [""])[0]
        trade = next((r for r in trades if r["id"] == trade_id), None)
        if trade_id and not trade:
            raise ValueError("Unknown trade")
        result = {"symbol":symbol, "period":period, "trades":trades}
        start = now-step*150
        end = now
        if trade:
            start = int(trade["at"]) - step*6
            end = min(now, int(trade["updated"]) + step*4)
            # Use a coarser replay interval when needed to cover the entire position.
            for period, step in PERIODS.items():
                if end-start <= step*900:
                    break
            result["period"] = period
            result["replay"] = self.cached((symbol,trade_id,trade["updated"]),60,
                                           lambda: self.replay(symbol, trade))
        else:
            try:
                ticker = self.cached(("ticker",symbol),3,lambda: self.exchange.ticker(symbol))
                if ticker["symbol"] != symbol:
                    raise ValueError("Unexpected market")
                result["quote"] = {"time":epoch(ticker["timestamp"]), "mark":ticker.get("mark_price"),
                                   "price":ticker.get("close"), "bid":ticker["quotes"].get("best_bid"),
                                   "ask":ticker["quotes"].get("best_ask")}
                result["account"] = self.cached(("account",symbol),5,lambda: self.account(symbol,ticker))
            except Exception:
                pass
        if summary:
            return result

        if self.archive is not None and not trade and result.get("quote"):
            try:
                mark = float(result["quote"]["mark"])
                # Quote changes can change the nearest level across a pivot.
                result["historical_levels"] = self.cached(("levels",symbol,now//300,mark),5,
                    lambda: self.archive.levels(symbol,now,mark))
            except (sqlite3.Error, TypeError, ValueError):
                pass

        def bars():
            rows = self.exchange.candles(symbol=symbol,resolution=period,start=start,end=end)
            out = {}
            for row in rows:
                stamp = int(row["time"])
                prices = [float(row[k]) for k in ("open","high","low","close")]
                if all(math.isfinite(p) and p > 0 for p in prices):
                    out[stamp] = [stamp,*prices]
            return [out[k] for k in sorted(out)]
        try:
            result["bars"] = self.cached(("bars",symbol,period,trade_id,start if trade else 0),
                                         300 if trade else 4,bars)
        except Exception:
            result["bars"] = []
        return result

    def replay(self, symbol, trade):
        result = trade.copy()
        ids = dict(trade.get("exit_order_ids") or {})
        if trade.get("broker_order_id"):
            ids["entry"] = trade["broker_order_id"]
        verified = {}
        for kind, order_id in ids.items():
            if not str(order_id).isdigit():
                continue
            try:
                order = self.exchange._request("GET", "/v2/orders/"+str(order_id), auth=True)["result"]
                if (str(order["id"]) != str(order_id) or (order.get("product_symbol") or order.get("symbol")) != symbol
                        or order["state"] != "closed" or Decimal(str(order["unfilled_size"])) != 0
                        or Decimal(str(order["average_fill_price"])) <= 0):
                    continue
                result[kind] = {"price":order["average_fill_price"], "at":epoch(order["updated_at"]),
                                "commission":order.get("paid_commission")}
                verified[kind] = order
            except Exception:
                continue
        if trade.get("id"):
            result["scorecard"] = self.scorecard(symbol, trade, verified)
        return result

    def scorecard(self, symbol, trade, orders):
        # Expose only market context from the private snapshot, never wallet data.
        with closing(self.stores[symbol]._connect()) as db:
            has_inputs = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                    "AND name='fire_model_inputs'").fetchone()
            row = db.execute("SELECT snapshot FROM fire_model_inputs WHERE press=?",
                             (trade.get("id"),)).fetchone() if has_inputs else None
        snapshot = json.loads(row[0]) if row else {}
        core = snapshot.get("core", {})
        tech = snapshot.get("technical", {})
        card = {"quote": trade.get("decision_quote") or {
                    "best_bid": core.get("best_bid"), "best_ask": core.get("best_ask")},
                "snapshot_at": snapshot.get("collected_at") or trade.get("snapshot_at"),
                "return_1h_pct": tech.get("return_1h_pct"),
                "realized_vol_1h_pct": tech.get("realized_vol_1h_pct"),
                "moves": {}, "exit": None}
        exits = [k for k in ("stop_loss_order","take_profit_order") if k in orders]
        if len(exits) == 1:
            card["exit"] = exits[0]
        entry = orders.get("entry")
        exit_fill = orders.get(card["exit"])
        if entry and exit_fill:
            side = trade.get("direction")
            try:
                units = Decimal(str((trade.get("budget") or {}).get("contract_value")
                                    or core["ticker"]["contract_value"]))
                qty = Decimal(str(entry["size"]))
                if (side in ("LONG","SHORT") and units.is_finite() and units > 0 and qty > 0
                        and qty == Decimal(str(exit_fill["size"])) == trade["contracts"]
                        and entry["side"] == ("buy" if side == "LONG" else "sell")
                        and exit_fill["side"] != entry["side"] and exit_fill["side"] in ("buy","sell")):
                    change = Decimal(str(exit_fill["average_fill_price"])) - Decimal(str(entry["average_fill_price"]))
                    gross = units * qty * change * (1 if side == "LONG" else -1)
                    fees = sum(Decimal(str(o["paid_commission"])) for o in (entry, exit_fill))
                    if fees.is_finite() and gross.is_finite():
                        card.update(fees_usd=str(fees), pnl_after_fees_usd=str(gross-fees))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                pass
        at = epoch(card["snapshot_at"])
        quote = card["quote"]
        if not at or not quote.get("best_bid") or not quote.get("best_ask"):
            return card
        midpoint = (Decimal(str(quote["best_bid"])) + Decimal(str(quote["best_ask"]))) / 2
        if not midpoint.is_finite() or midpoint <= 0:
            return card
        # Use the last completed one-minute candle at each horizon (up to 59s earlier).
        start = int(at // 60) * 60
        now = int(time.time())
        due = [m for m in (5, 15, 30) if at + m*60 <= now]
        if due:
            try:
                candles = self.exchange.candles(symbol=symbol,resolution="1m",start=start,
                                                end=start+max(due)*60)
                closes = {int(c["time"]): Decimal(str(c["close"])) for c in candles}
                for m in due:
                    close = closes.get(start+(m-1)*60)
                    if close and close.is_finite() and close > 0:
                        card["moves"][str(m)] = round(float(100*(close/midpoint-1)), 4)
            except (KeyError, TypeError, ValueError, ArithmeticError, RuntimeError, OSError):
                pass
        return card
