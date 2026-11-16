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
    return ("BTC" in symbol and kind in {
        "perpetual_futures", "futures", "call_options", "put_options"
    } and product.get("state") == "live")


class DeltaDemo:
    def __init__(self, api_key: str = "", api_secret: str = "",
                 allow_orders: bool = False):
        self.api_key, self.api_secret = api_key, api_secret
        self.allow_orders = allow_orders
        self.base_url = DEMO_API  # Never accept a caller-provided host.

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
        req = Request(self.base_url + path + query, headers=headers,
                      data=body.encode() if body else None, method=method.upper())
        try:
            with urlopen(req, timeout=8) as response:
                message = json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise DeltaError(f"Demo exchange request failed: {exc}") from exc
        if message.get("success") is not True:
            raise DeltaError(f"Delta demo API rejected request: {message.get('error')}")
        return message

    def products(self, *, limit_pages: int = 10) -> list[dict]:
        """Paginate active derivatives catalog; fail if pagination may be incomplete."""
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
