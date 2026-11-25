"""Minimal Delta India demo API, adapted from the original client."""
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

DEMO_API = "https://cdn-ind.testnet.deltaex.org"


# Only explicitly recognized exchange codes are retained. Never persist
# response bodies, arbitrary error messages, URLs, headers or credentials.
KNOWN_CODES=frozenset(("order_not_found","invalid_order","invalid_order_id",
    "insufficient_margin","insufficient_balance","invalid_stop_price",
    "invalid_price","invalid_size","invalid_api_key","invalid_signature",
    "signature_expired","rate_limit_exceeded","invalid_product",
    "invalid_bracket_order","invalid_order_type","invalid_request",
    "unauthorized","forbidden","not_found","internal_server_error",
    "invalid_stop_loss_price","invalid_take_profit_price"))
def safe_exchange_code(data):
    error=data.get("error") if isinstance(data,dict) else None
    code=error.get("code") if isinstance(error,dict) else None
    return code if isinstance(code,str) and code in KNOWN_CODES else (
        "unrecognized_exchange_code" if code is not None else None)

class BrokerError(RuntimeError):
    def __init__(self,message="Demo broker error",*,category="local_or_unclassified",http_status=None,exchange_code=None):
        super().__init__(message)
        self.category=category
        self.http_status=http_status
        self.exchange_code=exchange_code if exchange_code in KNOWN_CODES or exchange_code=="unrecognized_exchange_code" else None

def error_detail(exc):
    out={"error":type(exc).__name__}
    if isinstance(exc,BrokerError):
        out.update(category=exc.category,http_status=exc.http_status,exchange_code=exc.exchange_code)
    return out


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

    def _request(self, method, path, *, params=None, payload=None, auth=False, envelope=False):
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
                raw=response.read(8_000_001)
        except HTTPError as exc:
            status=exc.code
            code=None
            try:
                raw=exc.read(16385)
                if len(raw)<=16384:code=safe_exchange_code(json.loads(raw))
            except (OSError,ValueError,TypeError,AttributeError):
                pass
            finally:exc.close()
            raise BrokerError("Demo HTTP error",category="http_error",http_status=status,exchange_code=code) from None
        except (TimeoutError, URLError, OSError) as exc:
            reason=exc.reason if isinstance(exc,URLError) else exc
            category="timeout" if isinstance(reason,TimeoutError) else "transport_error"
            raise BrokerError("Demo transport error",category=category) from None
        if len(raw)>8_000_000:
            raise BrokerError("Demo response too large",category="invalid_response")
        try:data=json.loads(raw)
        except (ValueError,TypeError):
            raise BrokerError("Demo invalid JSON",category="invalid_response") from None
        if not isinstance(data, dict) or data.get("success") is not True or "result" not in data:
            raise BrokerError("Demo exchange rejected request or returned invalid response",
                category="exchange_rejection" if isinstance(data,dict) and data.get("success") is False else "invalid_response",
                exchange_code=safe_exchange_code(data))
        return data if envelope else data["result"]

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

    def product(self, symbol):
        return self._request("GET", "/v2/products/" + quote(symbol, safe=""))

    def wallet(self):
        return self._request("GET", "/v2/wallet/balances", auth=True, envelope=True)

    def positions(self, product_id):
        return self._request("GET", "/v2/positions", params={"product_id": product_id}, auth=True)

    def set_order_leverage(self, product_id):
        return self._request("POST", f"/v2/products/{product_id}/orders/leverage",
                             payload={"leverage": 20}, auth=True)

    def submit_bracket(self, intent, client_order_id):
        payload = {"product_id": intent.product_id, "side": intent.side,
                   "size": intent.size, "order_type": "market_order",
                   "reduce_only": False, "client_order_id": client_order_id,
                   "bracket_stop_loss_price": str(intent.stop_loss),
                   "bracket_take_profit_price": str(intent.take_profit),
                   "bracket_stop_trigger_method": "mark_price"}
        return self._request("POST", "/v2/orders", payload=payload, auth=True)

    def margined_positions(self, product_id):
        return self._request("GET", "/v2/positions/margined",
                             params={"product_ids": str(product_id)}, auth=True)

    def active_orders_page(self, product_id, after=None):
        params = {"product_ids": str(product_id), "page_size": 50}
        if after:
            params["after"] = after
        return self._request("GET", "/v2/orders", params=params, auth=True, envelope=True)

    def fills_page(self, product_id, after=None):
        params = {"product_ids": str(product_id), "page_size": 50}
        if after:
            params["after"] = after
        return self._request("GET", "/v2/fills", params=params, auth=True, envelope=True)
