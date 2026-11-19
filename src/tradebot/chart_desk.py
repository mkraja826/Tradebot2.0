"""Read-only chart data and per-market FIRE replay."""
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import json
import math
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

    def trades(self, symbol):
        with closing(self.stores[symbol]._connect()) as db:
            rows = db.execute("SELECT press,created_at,updated_at,status,result FROM fire_requests "
                              "ORDER BY created_at DESC LIMIT 40").fetchall()
        return [dict(json.loads(raw), id=key, at=epoch(at), updated=epoch(updated), status=status)
                for key, at, updated, status, raw in rows]

    def account(self, symbol, ticker):
        pid = ticker["product_id"]
        raw = self.exchange._request("GET", "/v2/positions", params={"product_id": pid}, auth=True)["result"]
        rows = [raw] if isinstance(raw, dict) else raw
        positions = []
        for row in rows:
            if str(row["product_id"]) != str(pid):
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
        trades = [] if summary else self.trades(symbol)
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
            except Exception:
                continue
        return result
