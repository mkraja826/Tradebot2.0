"""Explicit Gold demo mark controller, not installed or callable by the shadow worker."""
from .gold_v2_controller import Controller,verify_account,outstanding,status
from .gold_v2_recovery import synchronize_terminal_entries
from .gold_v2_mark_entry import prepare_mark,VERSION as ENTRY_VERSION,MODEL
from .gold_v2_hybrid import MARK_SOURCE
from .gold_v2_engine import quality,features

MANAGEMENT_SOURCE="delta_demo_mark_completed_bars"

def management_report(bars,as_of):
    q=quality(bars,300,as_of)
    return {"symbol":"XAUTUSD","signal_source":MANAGEMENT_SOURCE,
            "as_of":as_of,"status":"observed" if q=="observed" else "data_unusable",
            "data_quality":q,"features":{300:features(bars)} if q=="observed" else {}}

class MarkController(Controller):
    """Same account-scoped episode lifecycle, with explicit mark entry preparation."""
    def entry_cycle(self,reference,*,ref_ticker=None,reference_pid=None):
        if not self.enabled:return status("disabled",execution_effect="none")
        account=verify_account(self.broker,self.expected)
        synchronize_terminal_entries(self.orders,self.episodes,account)
        if outstanding(self.episodes) or self.orders.unresolved():
            return status("unresolved_episode_or_order")
        if self.pending_management():return status("unresolved_management")
        if reference.get("signal_source")!=MARK_SOURCE or reference.get("execution_eligible") is not False:
            return status("wrong_mark_source")
        anchor=self.clock()
        result,context=prepare_mark(self.broker,reference,ref_ticker,reference_pid=reference_pid,
             expected_gold_account=account,allocation_fraction=self.allocation,clock=self.clock)
        if result["status"]!="proposed":return status(result["status"])
        if result.get("version")!=ENTRY_VERSION or result.get("model_version")!=MODEL or result.get("signal_source")!=MARK_SOURCE:
            raise ValueError("wrong_prepared_source")
        provenance={k:result[k] for k in ("signal_source","model_version","entry_family","research_quote_pair")}
        return self._dispatch_prepared(reference["mark_report"],result,context,account,anchor,
                                       result["signal_atr"],provenance=provenance)

    def cycle(self,reference,history=(),*,ref_ticker=None,reference_pid=None,demo_as_of=None):
        if not self.enabled:return status("disabled",execution_effect="none")
        rows=outstanding(self.episodes)
        if len(rows)>1:return status("multiple_unresolved_episodes")
        if rows:
            seed=rows[0][1]
            if seed.get("signal_provenance",{}).get("signal_source")!=MARK_SOURCE:
                return status("wrong_episode_source")
            # Use demo-price bars, not absolute production levels. Even with
            # unavailable market history, reconcile receipts and exchange exits.
            at=int(self.clock()) if demo_as_of is None else demo_as_of
            report=management_report(history,at)
            return self.manage_cycle(report,history,seed)
        return self.entry_cycle(reference,ref_ticker=ref_ticker,reference_pid=reference_pid)
