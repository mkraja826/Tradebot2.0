"""Additive read-only FastMCP tools for the separately hosted Tb2.0 server.

Register once before the existing mcp.run(). Trusted operator selects roots;
callers cannot supply paths, commands, credentials, or deployment targets.
"""
import json
import time
from pathlib import Path
from typing import Literal
from . import (trade_intelligence, gold_entry_intelligence, capital_intelligence,
               position_intelligence, cost_intelligence, regime_intelligence,
               learning_intelligence, research_validation)
Market=Literal["BTCUSD","XAUTUSD"]
MARKETS=("BTCUSD","XAUTUSD")
VERSION="tb2-intelligence-tools-v1"
MAX_ITEMS=20
MAX_WINDOW=31*86400

def register(mcp, *, data_dir, learning_dir, audit_file=None):
    data=Path(data_dir).resolve()
    learning=Path(learning_dir).resolve()
    audit=Path(audit_file).resolve() if audit_file is not None else None
    def market(symbol):
        if symbol not in MARKETS:raise ValueError("unsupported demo symbol")
        return data/symbol
    def limit_value(limit):
        if type(limit) is not int or not 1<=limit<=MAX_ITEMS:raise ValueError("limit must be 1..20")
        return limit
    def window(start,end):
        if type(start) is not int or type(end) is not int or not 0<=start<end<=int(time.time()) or end-start>MAX_WINDOW:
            raise ValueError("use historical UTC epochs, maximum 31 days")
    def invoke(fn,*args):
        try:
            r=fn(*args);json.dumps(r,allow_nan=False)
            if r.get("execution_effect")!="none":return {"status":"unexpected_report_contract","execution_effect":"none"}
            return r
        except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError,OSError) as e:
            return {"status":"report_error","error_type":type(e).__name__,"execution_effect":"none"}
    def bounded(r,limit,key="trades"):
        if key not in r:return r
        values=r[key]
        return {**r,key:values[-limit:],"returned_items":min(limit,len(values)),"available_items":len(values)}
    @mcp.tool()
    def research_status():
        """Check availability of the separate BTC and Gold research journals and saved audit. Read-only."""
        return {"version":VERSION,"execution_effect":"none","symbols":{s:{f:(market(s)/f).is_file()
            for f in research_validation.FILES} for s in MARKETS},
            "learning_journal_available":(learning/"learning.sqlite").is_file(),
            "saved_validation_available":bool(audit and audit.is_file()),
            "deployment_access":False,"trade_mutation_access":False}
    @mcp.tool()
    def trade_intelligence_report(symbol:Market,limit:int=10):
        """Read reconciled trade intelligence, original model rationale and evidence quality for recent episodes."""
        return bounded(invoke(trade_intelligence.report,market(symbol),symbol,learning),limit_value(limit))
    @mcp.tool()
    def gold_entry_report(limit:int=10):
        """Read archived Gold entry evidence, signal-family conflicts, market structure and hypothetical costs."""
        return bounded(invoke(gold_entry_intelligence.report,market("XAUTUSD")),limit_value(limit))
    @mcp.tool()
    def capital_allocation_report(symbol:Market,limit:int=10):
        """Read historical capital allocation and estimated linear-contract monetary exposure; not actual margin."""
        return bounded(invoke(capital_intelligence.report,market(symbol),symbol),limit_value(limit))
    @mcp.tool()
    def position_management_report(symbol:Market,limit:int=10):
        """Read receipt-linked reduction/close evidence and observed profit retention diagnostics."""
        return bounded(invoke(position_intelligence.report,market(symbol),symbol),limit_value(limit))
    @mcp.tool()
    def trading_cost_report(symbol:Market,start:int,end:int,limit:int=10):
        """Read exchange commissions and recorded AI token usage in a bounded UTC epoch interval. No invented invoice rates."""
        window(start,end)
        return bounded(invoke(cost_intelligence.report,market(symbol),symbol,start,end),limit_value(limit))
    @mcp.tool()
    def market_regime_report(symbol:Market,split:int,end:int,limit:int=20):
        """Read chronological regime research and assumed cost sensitivity. Does not validate a policy."""
        window(split,end)
        r=invoke(regime_intelligence.report,market(symbol),symbol,split,end)
        return bounded(r,limit_value(limit),"groups")
    @mcp.tool()
    def learning_evidence_report(symbol:Market,cutoff:int):
        """Read reconciled observations enrolled before the historical UTC cutoff. Not live feedback or retraining."""
        if type(cutoff) is not int or not 0<cutoff<=int(time.time()):raise ValueError("invalid cutoff")
        rows=learning_intelligence.read_rows(learning/"learning.sqlite",symbol)
        market(symbol)
        return invoke(learning_intelligence.feedback,symbol,rows,cutoff)
    @mcp.tool()
    def saved_research_validation():
        """Read the last operator-generated unified validation summary, including its age and limitations. Does not run an audit."""
        if audit is None or not audit.is_file():return {"status":"audit_unavailable","execution_effect":"none"}
        try:
            with audit.open("rb") as f:
                raw=f.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:return {"status":"audit_too_large","execution_effect":"none"}
            r=json.loads(raw)
            if not isinstance(r,dict) or r.get("version")!=research_validation.VERSION or r.get("execution_effect")!="none":
                return {"status":"invalid_audit_contract","execution_effect":"none"}
            finished=r.get("snapshot_finished_utc")
            if type(finished) is not int or not 0<finished<=int(time.time()):
                return {"status":"invalid_audit_timestamp","execution_effect":"none"}
            # Explicit allowlist avoids passing arbitrary operator-file contents to callers.
            fields=("version","status","execution_effect","snapshot_started_utc","snapshot_finished_utc",
                    "copies","window","markets","candidate_policy_tested","profitability_improvement_validated",
                    "live_activation_ready","limitations")
            return {**{k:r.get(k) for k in fields},"audit_age_seconds":int(time.time())-finished}
        except (OSError,ValueError,TypeError):
            return {"status":"audit_unavailable_or_invalid","execution_effect":"none"}
