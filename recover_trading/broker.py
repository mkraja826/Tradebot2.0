"""Minimal Delta India demo API, adapted from the original client."""
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

DEMO_API = "https://cdn-ind.testnet.deltaex.org"


class BrokerError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def signature(secret, method, timestamp, path, query="", body=""):
    message = method.upper() + timestamp + path + query + body
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class DeltaDemo:
    def __init__(self, api_key="", api_secret="", *, opener=None):
        self._key = api_key
        self._secret = api_secret
        self._opener = opener or build_opener(NoRedirect())

    def _request(self, method, path, *, params=None, payload=None, auth=False):
        query = "?" + urlencode(params) if params else ""
        body = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "User-Agent": "recover-trading/0.1"}
        if auth:
            if not self._key or not self._secret:
                raise BrokerError("Demo credentials required")
            timestamp = str(int(time.time()))
            headers.update({"api-key": self._key, "timestamp": timestamp,
                            "signature": signature(self._secret, method, timestamp, path, query, body)})
        request = Request(DEMO_API + path + query, headers=headers,
                          data=body.encode() if payload is not None else None, method=method)
        try:
            with self._opener.open(request, timeout=10) as response:
                data = json.load(response)
        except (OSError, ValueError) as exc:
            raise BrokerError(f"Demo request failed: {type(exc).__name__}") from None
        if not isinstance(data, dict) or data.get("success") is not True or "result" not in data:
            raise BrokerError("Demo exchange rejected request or returned invalid response")
        return data["result"]

    def ticker(self, symbol):
        return self._request("GET", "/v2/tickers/" + quote(symbol, safe=""))

    def submit(self, intent, client_order_id):
        payload = {"product_id": intent.product_id, "side": intent.side,
                   "size": intent.size, "order_type": "market_order",
                   "reduce_only": intent.reduce_only, "client_order_id": client_order_id}
        return self._request("POST", "/v2/orders", payload=payload, auth=True)

    def order(self, client_order_id):
        return self._request("GET", "/v2/orders/client_order_id/" +
                             quote(client_order_id, safe=""), auth=True)
