"""Read-only reference-to-demo price compatibility research. No order payloads."""
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
from .gold_v2_entry_adapter import positive,dec
from .gold_v2_reference import SOURCE
from .entry_quotes import quote_evidence

VERSION="gold-v2-hybrid.2"
MARK_SOURCE="corroborated_production_mark"

def preview(reference,reference_ticker,demo_ticker,*,reference_pid,demo_pid,tick_size,now):
    return _preview(reference,reference_ticker,demo_ticker,reference_pid=reference_pid,demo_pid=demo_pid,
                    tick_size=tick_size,now=now,source=SOURCE,report_key="strict_reference_report")

def preview_mark(reference,reference_ticker,demo_ticker,*,reference_pid,demo_pid,tick_size,now):
    return _preview(reference,reference_ticker,demo_ticker,reference_pid=reference_pid,demo_pid=demo_pid,
                    tick_size=tick_size,now=now,source=MARK_SOURCE,report_key="mark_report")

def _preview(reference,reference_ticker,demo_ticker,*,reference_pid,demo_pid,tick_size,now,source,report_key):
    def out(s,**kw):return {"version":VERSION,"symbol":"XAUTUSD","status":s,
        "signal_source":source,"execution_eligible":False,"execution_effect":"none",**kw}
    try:
        if reference.get("symbol")!="XAUTUSD" or reference.get("signal_source")!=source:
            return out("wrong_reference")
        r=reference[report_key]
        if r.get("symbol")!="XAUTUSD" or r.get("signal_source")!=source or r.get("status")!="observed":
            return out("reference_data_unusable")
        if source==MARK_SOURCE and (r.get("version")!="gold-v2-mark-model.1" or r.get("execution_eligible") is not False):
            return out("wrong_mark_model")
        stamp=r["as_of"]
        if type(stamp) is not int or stamp!=reference["as_of"] or not 0<=now-stamp<=120 or int(now)//300!=stamp//300:
            return out("stale_signal")
        if type(reference_pid) is not int or type(demo_pid) is not int or min(reference_pid,demo_pid)<=0:
            return out("product_identity_unverified")
        ref=quote_evidence(reference_ticker,"XAUTUSD",reference_pid,int(now*1e6))
        demo=quote_evidence(demo_ticker,"XAUTUSD",demo_pid,int(now*1e6))
        if ref["status"]!="fresh_book" or demo["status"]!="fresh_book":
            return out("quote_unavailable")
        if abs(ref["timestamp_us"]-demo["timestamp_us"])>5_000_000:
            return out("quote_pair_not_synchronous")
        rp,dp=positive(ref["mark_price"]),positive(demo["mark_price"])
        bid,ask=positive(demo["best_bid"]),positive(demo["best_ask"])
        ref_bid,ref_ask=positive(ref["best_bid"]),positive(ref["best_ask"])
        ref_mid=(ref_bid+ref_ask)/2;demo_mid=(bid+ask)/2
        diagnostics={"mark_basis_bps":float((dp/rp-1)*10000),
                     "book_basis_bps":float((demo_mid/ref_mid-1)*10000),
                     "quote_skew_ms":abs(ref["timestamp_us"]-demo["timestamp_us"])//1000,
                     "reference_spread_bps":ref["spread_bps"],"demo_spread_bps":demo["spread_bps"],
                     "reference_mark":str(rp),"demo_mark":str(dp),
                     "reference_quote_timestamp_us":ref["timestamp_us"],"demo_quote_timestamp_us":demo["timestamp_us"]}
        candidates=r.get("candidates",[])
        if not candidates:return out("no_candidate",quotes=diagnostics)
        sides={c["direction"] for c in candidates}
        if len(sides)!=1 or r.get("conflicting_directions"):return out("conflicting_candidates",quotes=diagnostics)
        if not sides<={"LONG","SHORT"}:return out("invalid_direction",quotes=diagnostics)
        tick=positive(tick_size);plans=[]
        for c in candidates:
            side=1 if c["direction"]=="LONG" else -1
            entry=ask if side==1 else bid
            # Preserve fractional reference volatility, not the absolute trigger.
            atr=positive(c["atr"]);base=positive(c["reference_close"])
            normalized=atr/base;distance=entry*normalized
            sl0=entry-side*distance*positive(c["stop_distance_atr_hypothesis"])
            tp0=entry+side*distance*positive(c["target_distance_atr_hypothesis"])
            rounding=ROUND_FLOOR if side==1 else ROUND_CEILING
            sl=(sl0/tick).to_integral_value(rounding=rounding)*tick
            tp=(tp0/tick).to_integral_value(rounding=rounding)*tick
            geometry=min(sl,tp)>0 and (sl<min(entry,dp)<=max(entry,dp)<tp if side==1 else tp<min(entry,dp)<=max(entry,dp)<sl)
            plans.append({"family":c["family"],"direction":c["direction"],"demo_book_entry_reference":str(entry),
                          "reference_atr_fraction":str(normalized),"translated_atr":str(distance),
                          "hypothetical_stop":str(sl),"hypothetical_target":str(tp),
                          "mark_geometry_compatible":geometry})
        return out("hypotheses_observed",quotes=diagnostics,hypotheses=plans,
                   mapping="fractional_reference_atr_times_demo_book_price",
                   basis_acceptance_threshold="not_calibrated",fill_price="not_observed")
    except (KeyError,ValueError,TypeError,ArithmeticError,AttributeError):
        return out("invalid_evidence")
