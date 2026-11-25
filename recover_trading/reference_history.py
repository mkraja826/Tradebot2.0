"""Public production candles for OFFLINE research only; no authenticated requests."""
import json
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def candles(symbol,frame,end,count,*,opener=None):
    if symbol not in MARKETS or frame not in FRAMES or type(count) is not int or not 1<=count<=1900:
        raise ValueError("invalid reference request")
    step=FRAMES[frame]
    if type(end) is not int or end%step or end<=count*step:
        raise ValueError("invalid reference window")
    url="https://api.india.delta.exchange/v2/history/candles?"+urlencode(
        {"symbol":symbol,"resolution":frame,"start":end-count*step,"end":end})
    request=Request(url,headers={"Accept":"application/json"},method="GET")
    with (opener or build_opener(NoRedirect())).open(request,timeout=15) as response:
        raw=response.read(8_000_001)
    if len(raw)>8_000_000:
        raise ValueError("oversize reference response")
    body=json.loads(raw)
    if body.get("success") is not True:
        raise ValueError("reference unavailable")
    return normalize(body["result"],frame,as_of=end,count=count)
