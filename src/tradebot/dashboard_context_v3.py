"""Loopback-only adapter to existing authorized read-only account dashboard."""
import json
from urllib.request import build_opener,ProxyHandler,HTTPRedirectHandler
from datetime import datetime,timezone
from tradebot.account_context_v3 import project,LABELS
from tradebot.product_context_v3 import account_unavailable

URL="http://127.0.0.1:8765/api/isolated/overview"
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("redirect_not_allowed")

def load_dashboard():
    opener=build_opener(ProxyHandler({}),NoRedirect())
    with opener.open(URL,timeout=8) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000: raise ValueError("oversized_dashboard")
    return json.loads(raw)

def read_accounts(loader=load_dashboard,*,now=None):
    try: report=loader()
    except Exception:
        return {s:account_unavailable(s) for s in LABELS}
    now=now or datetime.now(timezone.utc)
    result={}
    for s in LABELS:
        try: result[s]=project(report,s,now=now)
        except (ValueError,TypeError,KeyError,AttributeError): result[s]=account_unavailable(s)
    return result
