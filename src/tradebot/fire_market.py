"""Delta Demo perpetual instrument selected by the FIRE operator."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from tradebot.delta import DeltaDemo, DeltaError

SYMBOLS = ("BTCUSD", "XAUTUSD")


class FireMarket(DeltaDemo):
    def __init__(self, symbol, **credentials):
        super().__init__(**credentials)
        if symbol not in SYMBOLS:
            raise ValueError("Unsupported FIRE market")
        self.symbol = symbol
        self._product_id = None

    @property
    def product_id(self):
        if self._product_id is None:
            ticker = self.ticker(self.symbol)
            self._identify(ticker)
        return self._product_id

    def _identify(self, ticker):
        pid = ticker.get("product_id")
        if (ticker.get("symbol") != self.symbol or ticker.get("contract_type") != "perpetual_futures"
                or type(pid) is not int or pid <= 0 or self._product_id not in (None, pid)):
            raise DeltaError("Cannot identify selected perpetual")
        self._product_id = pid

    def positions(self):
        rows = self._request("GET", "/v2/positions", params={"product_id": self.product_id}, auth=True)["result"]
        if isinstance(rows, dict):
            # Delta's single-product result may contain only size and entry_price.
            if "size" not in rows:
                raise DeltaError("Missing position size for selected market")
            rows = [{"product_id": self.product_id, **rows}]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                str(row.get("product_id")) != str(self.product_id) for row in rows):
            raise DeltaError("Unexpected position for selected market")
        return rows

    def open_orders(self, **kwargs):
        pid = str(self.product_id)
        return [row for row in super().open_orders(**kwargs) if str(row["product_id"]) == pid]

    def close_exposure(self, pause):
        for _ in range(3):
            if self.open_orders():
                self.cancel_product_orders(self.product_id)
            for row in self.positions():
                size = Decimal(str(row["size"]))
                if size != size.to_integral_value():
                    raise DeltaError("Fractional position size")
                if size:
                    self._request("POST", "/v2/orders", auth=True, payload={
                        "product_id": self.product_id, "side": "sell" if size > 0 else "buy",
                        "size": abs(int(size)), "order_type": "market_order", "reduce_only": True,
                        "client_order_id": "fire-exit-" + uuid4().hex[:20]})
            if not any(Decimal(str(row["size"])) for row in self.positions()) and not self.open_orders():
                return
            pause(1)
        raise DeltaError("Selected market flatness unverified")

    def snapshot(self):
        from tradebot.market import _age_seconds, _balances, _candles, _prices
        ticker = self.ticker(self.symbol)
        now = datetime.now(timezone.utc)
        self._identify(ticker)
        if (ticker.get("product_trading_status") != "operational"
                or _age_seconds(ticker["timestamp"], now) > 60):
            raise DeltaError("Selected market unavailable")
        book = self._request("GET", "/v2/l2orderbook/" + self.symbol, params={"depth": 20})["result"]
        if _age_seconds(book["last_updated_at"], datetime.now(timezone.utc)) > 60:
            raise DeltaError("Stale order book")
        bid, ask = _prices(book, self.symbol)
        end = int(now.timestamp())
        candles = self.candles(symbol=self.symbol, resolution="5m", start=end-21600, end=end)
        fields = ("symbol", "product_id", "contract_type", "contract_value", "tick_size",
                  "mark_price", "spot_price", "funding_rate", "oi", "volume", "quotes")
        return {"environment": "delta-india-demo", "collected_at": now.isoformat(),
                "core": {"symbol": self.symbol, "best_bid": str(bid), "best_ask": str(ask),
                         "spread": str(ask-bid), "ticker": {key: ticker.get(key) for key in fields}},
                "technical": _candles(candles, now), "demo_funds": _balances(self.wallet_balances()),
                "position_contracts": sum(int(row["size"]) for row in self.positions())}


def positions_for_fire(exchange):
    return exchange.positions() if isinstance(exchange, FireMarket) else exchange.btc_positions()
