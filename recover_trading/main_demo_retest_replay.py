"""Replay BTC breakout/retest with a verified main-demo wallet as the sizing basis."""
import json
import os
import time
from decimal import Decimal
from .broker import DeltaDemo


def replay(bars, contracts, contract_value):
    trades = []
    i = 24
    while i + 18 < len(bars):
        window = bars[i - 24:i + 19]
        if any(b["time"] - a["time"] != 300 for a, b in zip(window, window[1:])):
            i += 1
            continue
        high = max(x["high"] for x in window[:24])
        low = min(x["low"] for x in window[:24])
        close = bars[i]["close"]
        if low <= close <= high:
            i += 1
            continue
        side, level = (1, high) if close > high else (-1, low)
        for j in range(i + 1, i + 7):
            bar = bars[j]
            if side * (bar["close"] - level) <= 0:
                break
            touched = bar["low"] <= level if side == 1 else bar["high"] >= level
            entry = bars[j + 1]["open"]
            if not touched or side * (bar["close"] - bar["open"]) <= 0 or side * (entry - level) <= 0:
                continue
            for bar in bars[j + 1:j + 13]:
                adverse, favorable = (bar["low"], bar["high"]) if side == 1 else (bar["high"], bar["low"])
                gross = side * (bar["close"] / entry - 1)
                if side * (bar["open"] / entry - 1) <= -0.004:
                    gross = side * (bar["open"] / entry - 1)
                    break
                if side * (adverse / entry - 1) <= -0.004:
                    gross = -0.004
                    break
                if side * (favorable / entry - 1) >= 0.012:
                    gross = 0.012
                    break
            size = contracts(entry)
            trades.append({"time": bars[j+1]["time"], "side": side, "contracts": size,
                           "estimated_net_usd": size * contract_value * entry * (gross - 0.0022)})
            break
        i += 19
    return trades


def main():
    broker = DeltaDemo(os.environ["MAIN_DEMO_API_KEY"], os.environ["MAIN_DEMO_API_SECRET"])
    wallet = broker.wallet()["result"]
    usd, = [row for row in wallet if row["asset_symbol"] == "USD"]
    if str(usd.get("user_id", "")) != str(int(os.environ["MAIN_DEMO_USER_ID"])):
        raise ValueError("Main demo wallet identity mismatch")
    product = broker.product("BTCUSD")
    if product["symbol"] != "BTCUSD" or product["contract_unit_currency"] != "BTC" or product["settling_asset"]["symbol"] != "USD":
        raise ValueError("Unexpected BTCUSD contract specification")
    value = Decimal(str(product["contract_value"]))
    balance = Decimal(str(usd["balance"]))
    if balance <= 0 or value <= 0:
        raise ValueError("Expected positive wallet balance and contract value")
    end = int(time.time()) // 300 * 300
    start = end - 3 * 86400
    candles = broker._request("GET", "/v2/history/candles", params={
        "symbol": "BTCUSD", "resolution": "5m", "start": start, "end": end})
    bars = sorted((x for x in candles if start <= x["time"] < end), key=lambda x: x["time"])
    if [b["time"] for b in bars] != list(range(start, end, 300)):
        raise ValueError("Incomplete three-day candle response")
    for bar in bars:
        for key in ("open", "high", "low", "close"):
            bar[key] = float(bar[key])
        if not 0 < bar["low"] <= min(bar["close"],bar["open"]) <= max(bar["close"],bar["open"]) <= bar["high"]:
            raise ValueError("Invalid OHLC candle")
    def contracts(entry):
        return int(balance * Decimal("0.20") * 20 / (value * Decimal(str(entry))))
    print(json.dumps({"mode": "main_demo_replay", "start": start, "end": end,
                      "trades": replay(bars, contracts, float(value))}))


if __name__ == "__main__":
    main()
