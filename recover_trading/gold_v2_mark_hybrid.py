"""Dedicated mark-price hybrid research collection. No credentials or orders."""
from .gold_v2_mark_reference import collect_mark
from .gold_v2_mark_aggregation import collect as collect_exact
from .gold_v2_mark_model import evaluate_mark
from .gold_v2_hybrid import MARK_SOURCE
from concurrent.futures import ThreadPoolExecutor

def observe_mark(demo,reference,stamp,*,capture=None):
    def ref_reader(params):return reference.get("/v2/history/candles",params)
    def demo_reader(params):return demo._request("GET","/v2/history/candles",params=params)["result"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        a=pool.submit(collect_mark,ref_reader,stamp)
        b=pool.submit(collect_mark,demo_reader,stamp)
        c=pool.submit(collect_exact,ref_reader,"5m",300,stamp//900*900,750)
        primary,health=a.result()
        peer,peer_health=b.result()
        fine=c.result()
    report=evaluate_mark(primary,peer,fine,stamp)
    if capture is not None:
        capture(primary, report)
    return {"symbol":"XAUTUSD","signal_source":MARK_SOURCE,"as_of":stamp,
            "execution_eligible":False,"mark_report":report,
            "feed_health":health,"peer_feed_health":peer_health}
