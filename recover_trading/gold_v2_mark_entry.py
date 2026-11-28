"""Mark-source-specific demo entry preparation. No dispatch or live mutation."""
from .gold_v2_entry_adapter import _plan_selected,positive,dec
from .gold_v2_hybrid import preview_mark,MARK_SOURCE
from .entry_quotes import quote_evidence
import time

VERSION="gold-v2-mark-entry.1"
MODEL="gold-v2-mark-model.2"

def plan_mark(reference,ref_ticker,demo_ticker,product,wallet,*,reference_pid,allocation_fraction,now):
    def no(s):return {"version":VERSION,"status":s,"execution_effect":"none"}
    if reference.get("signal_source")!=MARK_SOURCE or reference.get("execution_eligible") is not False:
        return no("wrong_source")
    report=reference.get("mark_report",{})
    if report.get("version")!=MODEL or report.get("execution_eligible") is not False:
        return no("wrong_model")
    preview=preview_mark(reference,ref_ticker,demo_ticker,reference_pid=reference_pid,
                         demo_pid=product["id"],tick_size=product["tick_size"],now=now)
    if preview["status"]!="hypotheses_observed":return no(preview["status"])
    if preview.get("conflicting_directions"):return no("conflicting_candidates")
    plans=preview["hypotheses"]
    if not plans or not all(p.get("mark_geometry_compatible") is True for p in plans):
        return no("incompatible_bracket")
    if len({(p["direction"],p["translated_atr"],p["hypothetical_stop"],p["hypothetical_target"]) for p in plans})!=1:
        return no("conflicting_bracket_parameters")
    p=sorted(plans,key=lambda p:p["family"])[0]
    candidate={"family":p["family"],"direction":p["direction"],"atr":p["translated_atr"],
               "stop_distance_atr_hypothesis":1.5,"target_distance_atr_hypothesis":3}
    # Only the mark-specific planner uses this normalized ATR; the original
    # research envelope stays research-only and cannot enter legacy select().
    q=quote_evidence(demo_ticker,"XAUTUSD",product["id"],int(now*1000000))
    result=_plan_selected(report,candidate,product,wallet,q,allocation_fraction=allocation_fraction,now=now)
    if result["status"]!="proposed":return result
    if (dec(result["proposal"]["stop_loss"])!=dec(p["hypothetical_stop"])
        or dec(result["proposal"]["take_profit"])!=dec(p["hypothetical_target"])):
        return no("translated_bracket_mismatch")
    return dict(result,version=VERSION,signal_source=MARK_SOURCE,model_version=MODEL,
                signal_atr=p["translated_atr"],research_quote_pair=preview["quotes"],
                entry_family=p["family"],dispatch_supported=False)

def prepare_mark(broker,reference,ref_ticker,*,reference_pid,expected_gold_account,
                 allocation_fraction,clock=time.time):
    expected=str(expected_gold_account)
    if not expected.isdigit() or int(expected)<=0 or int(expected)==26679287:
        raise ValueError("invalid_gold_account")
    wallet,=[w for w in broker.wallet()["result"] if w.get("asset_symbol")=="USD"]
    if str(wallet.get("user_id"))!=expected:raise ValueError("gold_wallet_mismatch")
    product=broker.product("XAUTUSD")
    if product.get("symbol")!="XAUTUSD" or type(product.get("id")) is not int:raise ValueError("wrong_product")
    pid=product["id"]
    positions=broker.positions(pid)
    if isinstance(positions,dict):positions=[positions]
    if not isinstance(positions,list) or any(p.get("product_id")!=pid for p in positions):
        raise ValueError("unverified_positions")
    page=broker.active_orders_page(pid)
    if not isinstance(page.get("result"),list) or not isinstance(page.get("meta"),dict) or page["meta"].get("after"):
        return {"status":"incomplete_orders","execution_effect":"none"},None
    if any(dec(p["size"])!=0 for p in positions) or page["result"]:
        return {"status":"existing_exposure","execution_effect":"none"},None
    ticker=broker.ticker("XAUTUSD");now=clock()
    result=plan_mark(reference,ref_ticker,ticker,product,wallet,reference_pid=reference_pid,
                     allocation_fraction=allocation_fraction,now=now)
    return result,{"product":{"id":pid,"symbol":"XAUTUSD"},
                   "decision_quote":quote_evidence(ticker,"XAUTUSD",pid,int(now*1e6))}
