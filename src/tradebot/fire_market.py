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
        """Reduce-only exit before cancelling protection; never leave a live
        position naked because an emergency close request failed.

        Send at most ONE close order per invocation. A timeout/ambiguous result
        is not a license to re-post. Preserve existing protective stops until
        signed position evidence confirms zero exposure.
        """
        def signed_size():
            rows = self.positions()
            nonzero = []
            for row in rows:
                try:
                    size = Decimal(str(row["size"]))
                except (ValueError, ArithmeticError, KeyError, TypeError):
                    raise DeltaError("Unverified position size") from None
                if not size.is_finite() or size != size.to_integral_value():
                    raise DeltaError("Non-integral exchange position size")
                if size:
                    nonzero.append(size)
            if len(nonzero) > 1:
                raise DeltaError("Multiple selected-market positions")
            return nonzero[0] if nonzero else Decimal(0)

        size = signed_size()
        if size:
            # Do not cancel bracket orders first: if the broker rejects or
            # loses the exit response, they must remain in place.
            self._request("POST", "/v2/orders", auth=True, payload={
                "product_id": self.product_id, "side": "sell" if size > 0 else "buy",
                "size": abs(int(size)), "order_type": "market_order", "reduce_only": True,
                "client_order_id": "fire-exit-" + uuid4().hex[:20]})
            for attempt in range(5):
                if signed_size() == 0:
                    break
                if attempt < 4:
                    pause(1)
            else:
                raise DeltaError("Reduce-only exit unconfirmed; protective orders preserved")

        # Only after the broker confirms zero position can protective child
        # orders be removed without briefly uncovering live exposure.
        if signed_size() != 0:
            raise DeltaError("Closeout flatness became unverified")
        if self.open_orders():
            self.cancel_product_orders(self.product_id)
        for attempt in range(3):
            if signed_size() == 0 and not self.open_orders():
                return
            if attempt < 2:
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
