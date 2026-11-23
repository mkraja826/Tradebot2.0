"""Signed, read-only, independently scoped BTC and Gold performance evidence.

Financial views have two disjoint meanings:
1. Wallet posted trading cash flows: complete broker-signed account-wide windows;
   not necessarily autonomous FIRE attributable or full realized trade P&L.
2. Closed FIRE trade P&L: ONLY when all owned broker orders, fills and wallet
   postings satisfy the existing strict fire_reconciliation.analyse contract.
Unknown funding, pagination, fills or order identities never become a $0 gain.
No orders, no AI calls, no DB writes, no cross-subaccount aggregation.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock, Thread
import json
import os
import sqlite3
import time

from tradebot.delta import DEMO_API
from tradebot.fire_reconciliation import (
    ReconciliationError, analyse, identifier, normalize_fill, normalize_posting,
    number, timestamp_us, unique)
from tradebot.isolated_dashboard import ACCOUNTS, _sqlite, _read_keyfile, _user_id
from tradebot.signed_margin_mode import _parent_signed_subaccount_mode

WINDOW_DAYS = 7
WINDOW_US = WINDOW_DAYS * 86400 * 1_000_000
MAX_RECEIPTS = 144
POSTED_TYPES = frozenset(("cashflow", "settlement", "funding",
    "commission", "commission_rebate", "liquidation_fee"))
EXTERNAL_TYPES = frozenset(("deposit", "withdrawal", "withdrawal_cancellation",
    "external_deposit", "sub_account_transfer", "conversion", "fund_deposit",
    "fund_withdrawal", "fund_wallet_deposit", "fund_wallet_withdrawal"))
FEE_TYPES = frozenset(("commission", "commission_rebate", "liquidation_fee"))
CLOSED = frozenset(("flat_verified", "aborted_flat", "cancelled_flat_verified"))
PENDING = frozenset(("protected_active", "reasoning", "submitting",
    "reconciling", "verifying_protection", "exposure_unknown", "created"))


def _utc(us):
    return datetime.fromtimestamp(us / 1_000_000, timezone.utc).isoformat()


def _amount(v):
    return format(v, "f")


def _read_trades(root, *, start_us, cutoff_us):
    """A bounded immutable snapshot; never initialize or alter FIRE ledgers."""
    name = "fire-ops.sqlite" if root.name == "btc-isolated" else "fire-xaut.sqlite"
    with _sqlite(root / name) as db:
        rows = db.execute(
            "SELECT press,created_at,status,result FROM fire_requests "
            "ORDER BY created_at DESC LIMIT ?", (MAX_RECEIPTS+1,)).fetchall()
    overflow = len(rows) > MAX_RECEIPTS
    if overflow:
        rows = rows[:MAX_RECEIPTS]
    out=[]
    for press, created, status, raw in rows:
        try:
            stamp=timestamp_us(created)
            if stamp < start_us:
                continue
            if not start_us <= stamp <= cutoff_us:
                raise ValueError("Receipt timestamp outside current broker window")
            payload=json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Invalid receipt")
            if not isinstance(press, str) or len(press)!=32 or not all(
                    x in "0123456789abcdef" for x in press):
                raise ValueError("Invalid FIRE ownership")
            out.append({"id":press, "created_at":created,
                        "at_us":stamp, "status":str(status), "body":payload})
        except (ReconciliationError, ValueError, TypeError):
            raise ValueError("Malformed local FIRE receipt") from None
    return out, overflow


def _cashflows(postings, *, start_us, end_us):
    """Posted wallet movements in USD, with external transfers excluded.

    Signed wallet history is account-wide. This is NEVER a sum attributed to
    the AI strategy, nor a replacement for complete fill-level reconciliation.
    """
    partitions={}
    for name, boundary in (("last_24h",end_us-86400*1_000_000),
                           ("last_7d",start_us)):
        values={k:Decimal(0) for k in ("gross_cashflow_usd", "fees_usd",
                                       "funding_usd")}
        included=excluded=unknown=0
        for p in postings:
            if p["at_us"] < boundary or p["at_us"] > end_us:
                continue
            if p["type"] in EXTERNAL_TYPES:
                excluded += 1
                continue
            if p["type"] not in POSTED_TYPES or p["asset"] != "USD":
                unknown += 1
                continue
            amount=number(p["amount"])
            key=("fees_usd" if p["type"] in FEE_TYPES else
                 "funding_usd" if p["type"]=="funding" else "gross_cashflow_usd")
            values[key]+=amount
            included+=1
        net=sum(values.values(),Decimal(0))
        partitions[name]={
            "status":"verified_posted_cashflow" if not unknown else
                "unclassified_postings",
            "posted_net_usd":_amount(net) if not unknown else None,
            "gross_cashflow_usd":_amount(values["gross_cashflow_usd"]) if not unknown else None,
            "fees_usd":_amount(values["fees_usd"]) if not unknown else None,
            "funding_usd":_amount(values["funding_usd"]) if not unknown else None,
            "included_postings":included, "excluded_external_transfers":excluded,
            "unclassified_postings":unknown,
            "is_strategy_attributed":False,
            "is_verified_trade_pnl":False,
        }
    return partitions


def _trade_result(symbol, row, product, broker, fills, postings, start, end):
    trade=row["body"]
    base={
        "time":row["created_at"], "symbol":symbol,
        "model":str(trade.get("model") or "")[:55],
        "status":row["status"][:45],
        "direction":trade.get("direction") if trade.get("direction") in ("LONG","SHORT") else None,
        "contracts":trade.get("contracts") if type(trade.get("contracts")) is int else None,
        "leverage":trade.get("selected_leverage") if type(trade.get("selected_leverage")) is int else None,
        "net_realized_pnl_usd":None, "gross_realized_pnl_usd":None,
        "fees_usd":None, "funding_usd":None,
        "is_net_realized_pnl":False, "reconciliation_status":"unverified",
        "reason":"pending_complete_broker_evidence",
    }
    if row["status"] == "rejected_no_order" and trade.get("orders_submitted") is False:
        return dict(base,reconciliation_status="no_order",
                    reason="broker_order_not_submitted"),None
    if row["status"] not in CLOSED:
        return dict(base,reconciliation_status="position_open_or_unresolved",
                    reason="broker_finality_not_established"),None
    owned=dict(trade, id=row["id"], created_at=row["created_at"], status=row["status"])
    try:
        entry=identifier(trade.get("broker_order_id"))
        children={identifier(x) for x in (trade.get("exit_order_ids") or {}).values()}
        if not children or entry in children or len(children)!=2:
            raise ReconciliationError("entry_or_protective_orders_missing")
        orders={}
        for oid in sorted({entry}|children):
            orders[oid]=broker._request("GET","/v2/orders/"+oid,auth=True)["result"]
        result=analyse(symbol,owned,product,orders,fills,postings,start,end)
        if result.get("is_net_realized_pnl") is not True:
            return dict(base,reason="net_broker_evidence_incomplete"),None
        selected=(
            result["matched_fill_ids"],result["matched_posting_ids"])
        return dict(base,net_realized_pnl_usd=result["net_realized_pnl_usd"],
            gross_realized_pnl_usd=result["gross_realized_pnl_usd"],
            fees_usd=result["reconciled_fees_usd"],
            funding_usd=result["funding_cashflow_usd"],
            is_net_realized_pnl=True,
            reconciliation_status="broker_reconciled",
            reason="matched_order_fill_and_wallet_postings"),selected
    except ReconciliationError as exc:
        return dict(base,reason=str(exc)[:75]),None
    except Exception:
        return dict(base,reason="broker_order_evidence_unavailable"),None


def collect_account_performance(broker, root, symbol, *, now=None):
    """Perform ONLY signed GETs, limited to a complete past seven-day window."""
    if (broker.base_url != DEMO_API or broker.allow_orders is not False
            or symbol not in ("BTCUSD","XAUTUSD")
            or root.name != ("btc-isolated" if symbol=="BTCUSD" else "gold-isolated")
            or root.is_symlink() or not root.is_dir()):
        raise ValueError("Signed isolated DEMO history source required")
    instant=now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("Timezone-aware clock required")
    end=int(instant.timestamp()*1_000_000)
    start=end-WINDOW_US
    rows, overflow=_read_trades(root,start_us=start,cutoff_us=end)
    product=broker._request("GET","/v2/products/"+symbol)["result"]
    if (not isinstance(product,dict) or product.get("symbol")!=symbol
            or type(product.get("id")) is not int or product["id"]<=0):
        raise ValueError("Wrong broker product in performance report")
    # Both endpoints prove complete pagination, or they raise. No partial
    # account totals or 7-day strategy results are exposed.
    raw_fills=broker.product_fills(product["id"],start_time_us=start,end_time_us=end)
    raw_postings=broker.wallet_postings(start,end)
    fills=unique([normalize_fill(f) for f in raw_fills])
    postings=unique([normalize_posting(p) for p in raw_postings])
    if any(not start <= r["at_us"] <= end for r in fills+postings):
        raise ValueError("Evidence timestamp outside complete requested window")
    outcomes=[]; claimed={}; conflicted=set()
    for row in rows:
        item,owned=_trade_result(symbol,row,product,broker,fills,postings,start,end)
        if owned:
            for kind, ids in (("fill",owned[0]),("posting",owned[1])):
                for eid in ids:
                    key=(kind,eid)
                    if key in claimed:
                        conflicted.update((claimed[key],row["id"]))
                    else:
                        claimed[key]=row["id"]
        outcomes.append((row["id"],item))
    if conflicted:
        outcomes=[
            (key, dict(item,net_realized_pnl_usd=None,
                gross_realized_pnl_usd=None, fees_usd=None,funding_usd=None,
                is_net_realized_pnl=False,reconciliation_status="unverified",
                reason="broker_evidence_shared_between_trades")
                if key in conflicted else item)
            for key,item in outcomes]
    trades=[item for _,item in outcomes]
    verified=[r for r in trades if r["is_net_realized_pnl"]]
    pnl=[number(r["net_realized_pnl_usd"]) for r in verified]
    total=sum(pnl,Decimal(0))
    wins=sum(x>0 for x in pnl)
    losses=sum(x<0 for x in pnl)
    return {
        "status":"complete_broker_window", "symbol":symbol,
        "source":"signed_delta_india_demo_readonly",
        "as_of":instant.isoformat(), "window_start":_utc(start),
        "window_days":WINDOW_DAYS,"is_account_net_realized_pnl":False,
        "is_verified_strategy_profitability":False,
        "history_truncated":overflow,
        "wallet":_cashflows(postings,start_us=start,end_us=end),
        "signed_fill_count":len(fills),
        "signed_wallet_posting_count":len(postings),
        "fire_trade_count_in_window":len(trades),
        "broker_reconciled_closed_trades":len(verified),
        "unverified_or_open_trades":len(trades)-len(verified),
        "verified_subset_net_usd":_amount(total) if verified and not overflow else None,
        "verified_subset_win_rate_pct":_amount(Decimal(wins)*100/len(verified)) if verified and not overflow else None,
        "verified_subset_wins":wins,
        "verified_subset_losses":losses,
        "trade_rows":trades[:40],
        "warning":"Account wallet cash flow is not attributable FIRE net P&L. "
                  "Only completely reconciled closed FIRE outcomes are counted; "
                  "unverified trade profit remains unknown.",
    }


class IsolatedPerformanceDashboard:
    """Independently refreshes expensive signed broker histories every 5min."""

    def __init__(self, accounts, *, refresh_seconds=300):
        self.accounts=accounts
        self.refresh_seconds=max(120,int(refresh_seconds))
        self._lock=Lock()
        self._checked=float("-inf")
        self._updating=False
        self._report=self._blank()

    @staticmethod
    def _blank():
        return {"mode":"read_only","source":"isolated_signed_broker_performance",
                "checked_at":None,"window_days":WINDOW_DAYS,
                "accounts":{label:{"status":"loading"} for label in ACCOUNTS},
                "is_account_net_realized_pnl":False}

    def _account(self,label):
        dirname,symbol,*_=ACCOUNTS[label]
        root=self.accounts.root/dirname
        if root.is_symlink() or not root.is_dir():
            return {"status":"unavailable","reason":"private_account_scope_unavailable"}
        try:
            creds=self.accounts.credential_loader(self.accounts.keys/
                ("btc-demo-keys.env" if label=="BTC" else "gold-demo-keys.env"))
            child=self.accounts.client_factory(
                api_key=creds["DELTA_DEMO_API_KEY"],
                api_secret=creds["DELTA_DEMO_API_SECRET"],allow_orders=False)
            parent=self.accounts.client_factory(
                api_key=os.environ.get("DELTA_DEMO_API_KEY"),
                api_secret=os.environ.get("DELTA_DEMO_API_SECRET"),allow_orders=False)
            if (child.base_url!=DEMO_API or parent.base_url!=DEMO_API
                    or child.allow_orders is not False or parent.allow_orders is not False):
                raise ValueError("Read-only Delta demo identities required")
            prefs=child._request("GET","/v2/users/trading_preferences",auth=True)["result"]
            if not isinstance(prefs,dict):
                raise ValueError("Signed child identity missing")
            mode=_parent_signed_subaccount_mode(
                _user_id(prefs.get("user_id")),prefs.get("margin_mode"),
                parent_exchange=parent,expected_label=label)
            if mode!="isolated":
                raise ValueError("Signed child isolation unverified")
            return collect_account_performance(child,root,symbol)
        except Exception:
            return {"status":"unavailable","reason":"signed_history_or_reconciliation_unavailable",
                    "is_account_net_realized_pnl":False}

    def refresh(self):
        result=self._blank()
        result["checked_at"]=datetime.now(timezone.utc).isoformat()
        for label in ACCOUNTS:
            result["accounts"][label]=self._account(label)
        with self._lock:
            self._report=result
            self._updating=False
        return result

    def snapshot(self):
        with self._lock:
            if not self._updating and time.monotonic()-self._checked>=self.refresh_seconds:
                self._checked=time.monotonic()
                self._updating=True
                Thread(target=self.refresh,daemon=True).start()
            return dict(self._report)
