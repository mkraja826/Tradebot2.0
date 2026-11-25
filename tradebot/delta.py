"""Read-only compatibility adapter for recovered V3 market research."""
from recover_trading.broker import DeltaDemo as PublicDemo, DEMO_API


class DeltaDemo:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, api_key="", api_secret="", allow_orders=False):
        if allow_orders or api_key or api_secret:
            raise ValueError("Research adapter is public-data only")
        self._client = PublicDemo()

    def _request(self, method, path, *, params=None, **kwargs):
        if method != "GET" or not path.startswith("/v2/") or "://" in path or kwargs:
            raise ValueError("Public GET only")
        return {"result": self._client._request("GET", path, params=params)}

    def ticker(self, symbol):
        return self._client.ticker(symbol)

    def candles(self, *, symbol, resolution, start, end):
        return self._request("GET", "/v2/history/candles", params={
            "symbol": symbol, "resolution": resolution, "start": start, "end": end
        })["result"]
