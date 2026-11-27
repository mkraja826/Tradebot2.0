"""One-shot keyless hybrid observation. Dedicated journal, no execution."""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from .chart_reference import ReferenceClient
from .gold_v2_reference import observe_reference
from .gold_v2_hybrid import preview
from .gold_v2_hybrid_validation import HybridJournal
from tradebot.market_data_v3 import public_client

def collect(journal,*,quotes_only=False):
    demo=public_client();ref=ReferenceClient()
    product=demo._request("GET","/v2/products/XAUTUSD")["result"]
    rp=ref.get("/v2/products/XAUTUSD")
    if product.get("symbol")!="XAUTUSD" or rp.get("symbol")!="XAUTUSD":
        raise ValueError("wrong_product")
    stamp=int(time.time())
    reference=None if quotes_only else observe_reference(stamp,client=ref)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(ref.ticker,"XAUTUSD");b=pool.submit(demo.ticker,"XAUTUSD")
        rt,dt=a.result(),b.result()
    now=time.time()
    out={"execution_effect":"none","quote_record":journal.record_quote(dt,product["id"])}
    if reference is not None:
        packet=preview(reference,rt,dt,reference_pid=rp["id"],demo_pid=product["id"],
                       tick_size=product["tick_size"],now=now)
        out["reference_status"]=reference["strict_reference_report"]["status"]
        out["hybrid_status"]=packet["status"]
        out["quote_comparison"]=packet.get("quotes")
        try:out["enrollment"]=journal.enroll(packet,as_of=stamp)
        except ValueError:out["enrollment"]="expired_observation"
    out["resolved"]=journal.resolve()
    out["summary"]=journal.summary()
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--journal",required=True)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once",action="store_true")
    mode.add_argument("--quotes-only",action="store_true")
    mode.add_argument("--summary",action="store_true")
    args=p.parse_args()
    j=HybridJournal(args.journal)
    try:print(json.dumps(j.summary() if args.summary else collect(j,quotes_only=args.quotes_only),indent=2,allow_nan=False))
    finally:j.close()
if __name__=="__main__":main()
