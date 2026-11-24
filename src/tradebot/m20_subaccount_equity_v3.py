"""Offline transfer-aware child-account equity diagnostic, never a risk gate."""
from decimal import Decimal
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.signed_account_context_v3 import LABELS

CAPITAL_TYPES=frozenset(("deposit","withdrawal","withdrawal_cancellation","external_deposit","sub_account_transfer","fund_deposit","fund_withdrawal","fund_wallet_deposit","fund_wallet_withdrawal"))
def number(v):
    if isinstance(v,bool):raise ValueError("invalid_amount")
    d=Decimal(str(v))
    if not d.is_finite():raise ValueError("invalid_amount")
    return d

def analyse(symbol,opening,closing,postings,*,start_us,end_us,complete=False):
    """Normalized same-account fixture inputs; signed provenance is not implied."""
    if symbol not in LABELS or type(start_us) is not int or type(end_us) is not int or not 0<start_us<end_us:
        raise ValueError("invalid_scope")
    out={"mode":"offline_subaccount_equity_diagnostic","symbol":symbol,"subaccount":LABELS[symbol],
         "parent_equity_included":False,"execution_authorized":False,"broker_evidence_verified":False,
         "status":"unverified_window","adjusted_equity_change_usd":None,"posted_trading_cashflow_usd":None}
    if complete is not True:return out
    a,b=number(opening),number(closing)
    if a<=0 or b<0:raise ValueError("invalid_equity")
    capital=trade=Decimal(0);seen=set();unknown=0;counts={"capital":0,"trading":0}
    for p in postings:
        if p.get("symbol")!=symbol:raise ValueError("cross_account_posting")
        t=p["at_us"];i=p["id"]
        if type(t) is not int or not start_us<t<=end_us:raise ValueError("posting_outside_window")
        if not isinstance(i,str) or not i or i in seen:raise ValueError("duplicate_or_invalid_posting")
        seen.add(i)
        k=p["type"];v=number(p["amount"])
        if p.get("asset")!="USD":unknown+=1;continue
        if k in CAPITAL_TYPES:capital+=v;counts["capital"]+=1
        elif k in POSTED_TYPES:trade+=v;counts["trading"]+=1
        else:unknown+=1
    out.update({"counts":counts,"unclassified_count":unknown})
    if unknown:return dict(out,status="unclassified_postings")
    change=b-a-capital
    return dict(out,status="offline_calculated",net_capital_flow_usd=str(capital),
                adjusted_equity_change_usd=str(change),posted_trading_cashflow_usd=str(trade),
                unexplained_or_unrealized_change_usd=str(change-trade))
