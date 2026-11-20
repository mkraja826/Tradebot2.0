"""Delta India demo API client. Production URLs are deliberately unsupported."""
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEMO_API = "https://cdn-ind.testnet.deltaex.org"


class DeltaError(RuntimeError):
    pass


def signature(secret: str, method: str, timestamp: str, path: str,
              query: str = "", body: str = "") -> str:
    payload = method.upper() + timestamp + path + query + body
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def is_btc_contract(product: dict) -> bool:
    """Only BTC-labelled futures and option contracts are admitted."""
    symbol = str(product.get("symbol") or "").upper()
    kind = product.get("contract_type")
    return ((symbol.startswith("BTC") or symbol.startswith(("C-BTC-", "P-BTC-"))) and kind in {
        "perpetual_futures", "futures", "call_options", "put_options"
    } and product.get("state") == "live")


class DeltaDemo:
    def __init__(self, api_key: str = "", api_secret: str = "",
                 allow_orders: bool = False):
        self.api_key, self.api_secret = api_key, api_secret
        self.allow_orders = allow_orders
        # Endpoint intentionally not configurable: no live account support.

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 payload: dict | None = None, auth: bool = False) -> Any:
        if not path.startswith("/v2/") or "://" in path:
            raise ValueError("Invalid Delta v2 API path")
        query = ("?" + urlencode(params)) if params else ""
        body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "User-Agent": "tradebot2-demo/0.1"}
        if auth:
            if not self.api_key or not self.api_secret:
                raise DeltaError("Demo API key and secret are required")
            stamp = str(int(time.time()))
            headers.update({"api-key": self.api_key, "timestamp": stamp,
                            "signature": signature(self.api_secret, method, stamp, path, query, body)})
        if method.upper() != "GET" and not self.allow_orders:
            raise DeltaError("Order mutations disabled. Set ENABLE_DEMO_ORDERS=true only for demo.")
        req = Request(DEMO_API + path + query, headers=headers,
                      data=body.encode() if body else None, method=method.upper())
        try:
            with urlopen(req, timeout=8) as response:
                message = json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise DeltaError(f"Demo exchange request failed: {exc}") from exc
        if not isinstance(message, dict):
            raise DeltaError("Unexpected Delta API response")
        if message.get("success") is not True:
            raise DeltaError(f"Delta demo API rejected request: {message.get('error')}")
        return message

    def products(self, *, limit_pages: int = 100) -> list[dict]:
        """Paginate active derivatives catalog; fail if pagination may be incomplete."""
        if not isinstance(limit_pages, int) or not 1 <= limit_pages <= 200:
            raise ValueError("limit_pages must be 1..200")
        out, cursor = [], None
        for _ in range(limit_pages):
            params = {"states": "live", "page_size": "100",
                      "contract_types": "perpetual_futures,futures,call_options,put_options"}
            if cursor:
                params["after"] = cursor
            response = self._request("GET", "/v2/products", params=params)
            out.extend(x for x in response["result"] if is_btc_contract(x))
            next_cursor = (response.get("meta") or {}).get("after")
            if not next_cursor:
                return out
            if next_cursor == cursor:
                raise DeltaError("Pagination did not advance")
            cursor = next_cursor
        raise DeltaError("Product catalog truncated; increase limit_pages")

    def ticker(self, symbol: str) -> dict:
        from urllib.parse import quote
        if not symbol or not all(ch.isalnum() or ch in "-_" for ch in symbol):
            raise ValueError("Invalid symbol")
        return self._request("GET", "/v2/tickers/" + quote(symbol))["result"]

    def btc_positions(self) -> list[dict]:
        """Request only BTC-linked positions, never unrelated account positions."""
        response = self._request("GET", "/v2/positions",
                                 params={"underlying_asset_symbol": "BTC"}, auth=True)
        result = response["result"]
        return result if isinstance(result, list) else [result] if result else []

    def place_order(self, *, product: dict, side: str, size: int,
                    client_order_id: str, reduce_only: bool = False) -> dict:
        if not is_btc_contract(product):
            raise DeltaError("Order rejected: not a live BTC derivative")
        if side not in ("buy", "sell") or type(size) is not int or size <= 0:
            raise ValueError("Invalid side or contract quantity")
        if not client_order_id or len(client_order_id) > 32:
            raise ValueError("Client order ID must be 1-32 characters")
        payload = {"product_id": product["id"], "size": size, "side": side,
                   "order_type": "market_order", "reduce_only": reduce_only,
                   "client_order_id": client_order_id}
        return self._request("POST", "/v2/orders", payload=payload, auth=True)["result"]

    @property
    def base_url(self) -> str:
        """Read-only demo URL. Callers cannot change it to a production host."""
        return DEMO_API

    def open_orders(self, *, max_pages: int = 100) -> list[dict]:
        """Read every open/pending order page, or fail closed if incomplete."""
        if type(max_pages) is not int or not 1 <= max_pages <= 200:
            raise ValueError("max_pages must be 1..200")
        orders, after, seen = [], None, set()
        for _ in range(max_pages):
            params = {"states": "open,pending", "page_size": 50}
            if after:
                params["after"] = after
            reply = self._request("GET", "/v2/orders", params=params, auth=True)
            result = reply.get("result")
            if not isinstance(result, list) or any(not isinstance(v, dict) for v in result):
                raise DeltaError("Unexpected open orders response")
            orders.extend(result)
            meta = reply.get("meta") or {}
            if not isinstance(meta, dict):
                raise DeltaError("Malformed open-order pagination metadata")
            nxt = meta.get("after")
            if not nxt:
                return orders
            if nxt in seen:
                raise DeltaError("Open-order pagination loop")
            seen.add(nxt)
            after = nxt
        raise DeltaError("Open-order pagination incomplete: refuse closeout")

    def cancel_product_orders(self, product_id: int) -> None:
        if type(product_id) is not int or product_id <= 0:
            raise ValueError("Product ID must be a positive integer")
        self._request("DELETE", "/v2/orders/all", payload={
            "product_id": product_id,
            "cancel_limit_orders": True,
            "cancel_stop_orders": True,
            "cancel_reduce_only_orders": True,
        }, auth=True)

    def order_by_client_id(self, client_order_id: str) -> dict:
        from urllib.parse import quote
        if not client_order_id or not all(c.isalnum() or c in "-_" for c in client_order_id):
            raise ValueError("Invalid client order ID")
        result = self._request(
            "GET", "/v2/orders/client_order_id/" + quote(client_order_id),
            auth=True)
        if not isinstance(result.get("result"), dict):
            raise DeltaError("Unexpected order result")
        return result["result"]

    def btc_tickers(self) -> list[dict]:
        """Public BTC futures and option quotes, with Delta's documented filters."""
        response = self._request(
            "GET", "/v2/tickers",
            params={"underlying_asset_symbols": "BTC",
                    "contract_types": "perpetual_futures,futures,call_options,put_options"},
        )
        result = response.get("result")
        if not isinstance(result, list):
            raise DeltaError("Unexpected BTC ticker response")
        # Do not trust upstream filter alone.
        def btc_symbol(row):
            symbol = str(row.get("symbol") or "").upper()
            return (symbol.startswith("BTC") or symbol.startswith(("C-BTC-", "P-BTC-")))
        return [row for row in result if isinstance(row, dict) and btc_symbol(row)]

    def candles(self, *, symbol: str = "BTCUSD", resolution: str = "5m",
                start: int, end: int) -> list[dict]:
        """Return <=2000 time-ordered BTC OHLCV candles. Times are epoch seconds."""
        if symbol not in {"BTCUSD", "XAUTUSD"}:
            raise ValueError("Unsupported candle symbol")
        if resolution not in {"1m", "3m", "5m", "15m", "30m",
                              "1h", "2h", "4h", "6h", "1d", "1w"}:
            raise ValueError("Unsupported Delta candle resolution")
        if (type(start) is not int or type(end) is not int
                or start <= 0 or end <= start):
            raise ValueError("Invalid candle start/end epoch seconds")
        result = self._request(
            "GET", "/v2/history/candles",
            params={"resolution": resolution, "symbol": symbol,
                    "start": start, "end": end},
        ).get("result")
        if not isinstance(result, list) or not result or len(result) > 2000:
            raise DeltaError("Empty or malformed BTC candles response")
        return result

    def btc_orderbook(self, *, depth: int = 20) -> dict:
        """L2 BTCUSD book. Caller validates depth, timestamp and bid/ask spread."""
        if type(depth) is not int or not 1 <= depth <= 100:
            raise ValueError("depth must be 1..100")
        result = self._request(
            "GET", "/v2/l2orderbook/BTCUSD", params={"depth": depth}
        ).get("result")
        if not isinstance(result, dict) or result.get("symbol") != "BTCUSD":
            raise DeltaError("Malformed BTC order book response")
        return result

    def wallet_balances(self) -> dict:
        """Signed read-only demo balances; never sum across different assets."""
        reply = self._request("GET", "/v2/wallet/balances", auth=True)
        if not isinstance(reply.get("result"), list):
            raise DeltaError("Malformed demo wallet response")
        meta = reply.get("meta") or {}
        if not isinstance(meta, dict):
            raise DeltaError("Malformed wallet meta")
        return {"balances": reply["result"], "meta": meta}

    def wallet_postings(self, start_us, end_us):
        """Read a complete bounded window, deduplicating overlapping pages."""
        return self._account_history("/v2/wallet/transactions", start_us, end_us)

    def product_fills(self, product_id, *, start_time_us, end_time_us):
        """Complete signed fill window for one product, including partial fills."""
        if type(product_id) is not int or product_id <= 0:
            raise ValueError("Invalid product ID")
        rows = self._account_history("/v2/fills", start_time_us, end_time_us,
                                     product_ids=str(product_id))
        if any(str(row.get("product_id")) != str(product_id) for row in rows):
            raise DeltaError("Unexpected fill product")
        return rows

    def _account_history(self, path, start_us, end_us, **filters):
        if (type(start_us) is not int or type(end_us) is not int
                or start_us <= 0 or end_us <= start_us):
            raise ValueError("Invalid account history window")
        params = {"start_time": start_us, "end_time": end_us, "page_size": 100, **filters}
        rows, cursors = {}, set()
        for _ in range(40):
            reply = self._request("GET", path, params=params, auth=True)
            page, meta = reply.get("result"), reply.get("meta")
            # Absent metadata cannot establish complete financial history.
            if (not isinstance(page, list) or len(page) > 100
                    or any(not isinstance(row, dict) for row in page)
                    or not isinstance(meta, dict) or "after" not in meta):
                raise DeltaError("Invalid account history page")
            for row in page:
                identifier = row.get("id")
                if type(identifier) not in (str, int) or not str(identifier).strip():
                    raise DeltaError("Missing account history ID")
                key = str(identifier)
                if key in rows and rows[key] != row:
                    raise DeltaError("Inconsistent account history ID")
                rows[key] = row
            cursor = meta["after"]
            if cursor is None or cursor == "":
                return list(rows.values())
            if not isinstance(cursor, str) or cursor in cursors:
                raise DeltaError("Invalid account history cursor")
            params["after"] = cursor
            cursors.add(cursor)
        raise DeltaError("Incomplete account history window")

    def btc_fills(self, *, start_time_us: int, end_time_us: int,
                  max_pages: int = 40) -> list[dict]:
        """Read recent signed fills in <=50 record pages; no mutation.

        Delta may return products for multiple assets even with a contract-type
        filter; locally retain BTC fills only. This is a full requested-window
        read or an error, never silently truncated partial data.
        """
        if (type(start_time_us) is not int or type(end_time_us) is not int
                or start_time_us < 1 or end_time_us <= start_time_us):
            raise ValueError("Invalid fill window in epoch microseconds")
        if type(max_pages) is not int or not 1 <= max_pages <= 200:
            raise ValueError("Invalid max_pages")
        out, after, seen = [], None, set()
        for _ in range(max_pages):
            params = {
                "start_time": start_time_us, "end_time": end_time_us,
                "page_size": 50,
                "contract_types": "perpetual_futures,futures,call_options,put_options",
            }
            if after:
                params["after"] = after
            response = self._request("GET", "/v2/fills", params=params, auth=True)
            results = response.get("result")
            if not isinstance(results, list) or any(not isinstance(x, dict)
                                                    for x in results):
                raise DeltaError("Malformed fills response")
            for fill in results:
                symbol = str(fill.get("product_symbol") or "").upper()
                if symbol.startswith(("BTC", "C-BTC-", "P-BTC-")):
                    out.append(fill)
            meta = response.get("meta") or {}
            if not isinstance(meta, dict):
                raise DeltaError("Malformed fills pagination metadata")
            nxt = meta.get("after")
            if not nxt:
                return out
            if nxt in seen:
                raise DeltaError("Fills pagination loop")
            seen.add(nxt)
            after = nxt
        raise DeltaError("Fills pagination incomplete: refuse inaccurate summary")
