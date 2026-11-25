"""Unauthenticated, display-only production market reference client."""
import json
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode,quote
from tradebot.market_data_v3 import MARKETS,FRAMES
BASE="https://api.india.delta.exchange"
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None
class ReferenceClient:
    def get(self,path,params=None):
        url=BASE+path+("?" + urlencode(params) if params else "")
        with build_opener(NoRedirect()).open(Request(url,headers={"Accept":"application/json"},method="GET"),timeout=10) as r:
            raw=r.read(2_000_001)
        if len(raw)>2_000_000:
            raise ValueError("oversize reference response")
        data=json.loads(raw)
        if data.get("success") is not True:
            raise ValueError("reference unavailable")
        return data["result"]
    def candles(self,*,symbol,resolution,start,end):
        if symbol not in MARKETS or resolution not in FRAMES:
            raise ValueError("invalid market")
        return self.get("/v2/history/candles",dict(symbol=symbol,resolution=resolution,start=start,end=end))
    def ticker(self,symbol):
        if symbol not in MARKETS:
            raise ValueError("invalid market")
        return self.get("/v2/tickers/"+quote(symbol,safe=""))
