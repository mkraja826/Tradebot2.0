"""Bounded continuous keyless mark worker probe, not a deployment."""
import json,time
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from pathlib import Path
from .gold_v2_hybrid_worker import Study,product_info,publish
from .gold_v2_hybrid_validation import HybridJournal
from .gold_v2_hybrid import MARK_SOURCE
from .chart_reference import ReferenceClient
from .gold_v2_dashboard import read_mark_status
from tradebot.market_data_v3 import public_client

def main():
    with TemporaryDirectory() as tmp:
        root=Path(tmp)
        demo=public_client();ref=ReferenceClient()
        product,rp=product_info(demo,ref)
        journal=HybridJournal(root/"hybrid.sqlite",source=MARK_SOURCE)
        try:
            study=Study(journal,demo,ref,product,rp,source=MARK_SOURCE)
            events=[]
            with ThreadPoolExecutor(max_workers=1) as pool,ThreadPoolExecutor(max_workers=1) as macro_pool:
                start=time.monotonic()
                while time.monotonic()-start<75:
                    tick=time.monotonic()
                    event=study.cycle(pool,macro_pool)
                    events.append({"timestamp":event["timestamp"],"quote_record":event.get("quote_record"),
                                   "errors":event["errors"],"latest_signal":event["latest_signal"]})
                    publish(root,event)
                    time.sleep(max(0,10-(time.monotonic()-tick)))
            stamps=[r[0] for r in journal.db.execute("SELECT stamp FROM hybrid_quotes ORDER BY stamp")]
            result={"execution_effect":"none","cycles":len(events),"quote_count":len(stamps),
                    "max_internal_quote_gap_seconds":max(((b-a)/1e6 for a,b in zip(stamps,stamps[1:])),default=None),
                    "events":events,"dashboard":read_mark_status(root,int(time.time())),
                    "actual_fills":0}
            print(json.dumps(result,indent=2,allow_nan=False))
            if not stamps:raise RuntimeError("no_demo_quotes_observed")
        finally:journal.close()
if __name__=="__main__":main()
