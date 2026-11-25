"""Entry quote evidence and attribution; no order mutations or pricing constraints."""
from .performance import dec
def quote_evidence(ticker,symbol,pid,now_us):
    out={"status":"unavailable"}
    if not isinstance(ticker,dict) or ticker.get("symbol")!=symbol or ticker.get("product_id")!=pid:return out
    ts=ticker.get("timestamp")
    if type(ts) is not int or not 0<=now_us-ts<=30_000_000:return {"status":"stale_or_invalid"}
    out.update(timestamp_us=ts,age_ms=(now_us-ts)//1000)
    mark=dec(ticker.get("mark_price"))
    if mark is not None and mark>0:out["mark_price"]=str(mark)
    q=ticker.get("quotes")
    if not isinstance(q,dict):return out
    bid,ask=dec(q.get("best_bid")),dec(q.get("best_ask"))
    if bid is None or ask is None or not 0<bid<=ask:return out
    mid=(bid+ask)/2
    out.update(status="fresh_book",best_bid=str(bid),best_ask=str(ask),spread_bps=float((ask-bid)/mid*10000))
    for k in ("bid_size","ask_size"):
        v=dec(q.get(k))
        if v is not None and v>=0:out[k]=str(v)
    return out

def attribution(evidence,fill):
    """Signed adverse price differences, with common AI reference denominator."""
    if not isinstance(evidence,dict):return {}
    ref,avg=dec(evidence.get("reference")),dec(fill)
    sign=1 if evidence.get("side")=="buy" else -1 if evidence.get("side")=="sell" else None
    if sign is None or ref is None or avg is None or min(ref,avg)<=0:return {}
    key="best_ask" if sign==1 else "best_bid"
    def px(name):
        q=evidence.get(name)
        if not isinstance(q,dict) or q.get("status")!="fresh_book":return None
        p=dec(q.get(key));return p if p is not None and p>0 else None
    a,b=px("decision_quote"),px("pre_submit_quote")
    def bps(x,y):return float(sign*(x-y)/ref*10000)
    out={"total_reference_deviation_bps":bps(avg,ref)}
    if a is not None:out["reference_to_decision_book_bps"]=bps(a,ref)
    if a is not None and b is not None:out["decision_to_submission_book_bps"]=bps(b,a)
    if b is not None:out["submission_book_to_fill_bps"]=bps(avg,b)
    if a is not None and b is not None:out["complete_decomposition"]=True
    return out
