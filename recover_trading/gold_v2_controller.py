"""Gold V2 demo execution controller; disabled unless explicitly enabled by caller.

No CLI activation in this increment. Caller must establish exclusive Gold
execution ownership, operator-verified demo account and dedicated journals.
"""
import json
import time
from hashlib import sha256
from .broker import DeltaDemo,DEMO_API,BrokerError
from .execution import DemoExecutor
from .management_executor import ManagementExecutor
from .management_shadow import ManagementShadow
from .management_lifecycle import plan as validate_plan
from .gold_v2_entry_adapter import prepare,select
from .gold_v2_episode import client_id, timestamp, d
from .gold_v2_management_adapter import evaluate_episode
from .position_preview import observe
from .lifecycle import pages,normalize_fill
from .gold_v2_recovery import known_brackets,protective_receipts,local_no_submission,verify_no_submission,persist_no_submission,synchronize_terminal_entries

VERSION="gold-v2-controller.2"
SYMBOL="XAUTUSD"
TERMINAL=("closed","terminal_no_fill","terminal_no_submission")

def status(name,**kwargs):
    return {"version":VERSION,"symbol":SYMBOL,"status":name,**kwargs}

def verify_account(broker,expected):
    expected=str(expected)
    if not expected.isdigit() or int(expected)<=0 or int(expected)==26679287:
        raise ValueError("invalid_gold_account")
    wallet,=[w for w in broker.wallet()["result"] if w.get("asset_symbol")=="USD"]
    if str(wallet.get("user_id"))!=expected:raise ValueError("gold_wallet_mismatch")
    return expected

def outstanding(episodes):
    rows=episodes.db.execute("""SELECT e.client_id,e.seed,
        (SELECT result FROM gold_v2_episode_observations o WHERE o.client_id=e.client_id
         ORDER BY observed_at DESC LIMIT 1)
        FROM gold_v2_episodes e""").fetchall()
    return [(cid,json.loads(seed)) for cid,seed,last in rows if not last or json.loads(last)["status"] not in TERMINAL]

def stage_management(db,packet,*,now):
    """Stage a validated deterministic proposal in existing executor's schema."""
    if packet.get("symbol")!=SYMBOL or packet.get("status")!="proposal_prepared":
        raise ValueError("invalid_management_packet")
    c,p=packet["context"],packet["proposal"]
    if c.get("symbol")!=SYMBOL or p.get("symbol")!=SYMBOL:raise ValueError("wrong_symbol")
    validate_plan(c,p)
    boundary=packet["bar_boundary"]
    if type(boundary) is not int or boundary%300 or int(now)//300!=boundary//300:
        raise ValueError("stale_management_bucket")
    ident=sha256(f"gold-v2-management:{packet['entry_client_id']}:{boundary}".encode()).hexdigest()
    # Same bucket as legacy journal; never overwrite another proposal.
    raw=json.dumps(c,sort_keys=True,allow_nan=False)
    result=json.dumps({"proposal":p},sort_keys=True,allow_nan=False)
    with db:
        db.execute("BEGIN IMMEDIATE")
        inserted=db.execute("""INSERT OR IGNORE INTO management_shadow
            (id,symbol,bucket,created,model,status,context,result)
            VALUES (?,?,?,?,?,'proposed',?,?)""",
            (ident,SYMBOL,boundary//300,int(now),VERSION,raw,result)).rowcount
    return ident if inserted else None

class Controller:
    def __init__(self,broker,orders,episodes,*,expected_account,allocation_fraction,
                 enabled=False,clock=time.time):
        if type(broker) is not DeltaDemo or DEMO_API!="https://cdn-ind.testnet.deltaex.org":
            raise ValueError("demo_broker_required")
        self.broker=broker;self.orders=orders;self.episodes=episodes
        self.expected=str(expected_account);self.allocation=allocation_fraction
        self.enabled=enabled is True;self.clock=clock
        self.entry=DemoExecutor(broker,orders)
        self.manager=ManagementExecutor(broker,orders)
        self.shadow=ManagementShadow(orders.db)
    def entry_cycle(self,report):
        if not self.enabled:return status("disabled",execution_effect="none")
        account=verify_account(self.broker,self.expected)
        synchronize_terminal_entries(self.orders,self.episodes,account)
        if outstanding(self.episodes) or self.orders.unresolved():
            return status("unresolved_episode_or_order")
        if self.pending_management():return status("unresolved_management")
        # Anchor precedes the flat checks; any intervening fill makes replay fail.
        anchor=self.clock()
        result,context=prepare(self.broker,report,expected_gold_account=account,
                              allocation_fraction=self.allocation,clock=self.clock)
        if result["status"]!="proposed":return status(result["status"])
        candidate,_=select(report);p=result["proposal"]
        boundary=int(report["as_of"])//300*300;cid=client_id(boundary)
        if self.episodes.db.execute("SELECT 1 FROM gold_v2_episodes WHERE client_id=?",(cid,)).fetchone():
            return status("entry_bar_already_reserved")
        seed={"symbol":SYMBOL,"client_id":cid,"signal_boundary":boundary,
              "account_id":account,"product_id":context["product"]["id"],"side":p["side"],
              "size":p["size"],"stop_loss":p["stop_loss"],"take_profit":p["take_profit"],
              "signal_atr":candidate["atr"],"flat_verified":True,"flat_observed_at":anchor}
        # Durable seed BEFORE any order submission. If the process dies here,
        # reconcile/operator review is required, not blind retry.
        self.episodes.reserve(seed)
        receipt=self.entry.execute(result,account=context)
        return status("entry_dispatch",execution_status=receipt.get("status"))
    def pending_management(self):
        return self.orders.db.execute("""SELECT 1 FROM management_attempts WHERE symbol=?
            AND status IN ('attempting','outcome_unverified','partial_result_unverified') LIMIT 1""",(SYMBOL,)).fetchone() is not None
    def collect(self,seed):
        account=verify_account(self.broker,self.expected)
        if seed.get("account_id")!=account:raise ValueError("episode_account_mismatch")
        pid=seed["product_id"];product=self.broker.product(SYMBOL)
        if product.get("symbol")!=SYMBOL or product.get("id")!=pid:
            raise ValueError("episode_product_mismatch")
        try:
            receipt=self.broker.order(seed["client_id"])
        except BrokerError as exc:
            if exc.exchange_code!="order_not_found":raise
            raw,complete=pages(self.broker.fills_page,pid)
            fills=[normalize_fill(f)[1] for f in raw]
            snapshot=self.manager.reader.observe(SYMBOL,pid)
            now=int(self.clock())
            recovered=verify_no_submission(seed,fills,snapshot,now=now,complete=complete,
                local_reason=local_no_submission(self.orders,seed),error=exc)
            if recovered is not None:
                persist_no_submission(self.episodes,seed,recovered,now=now)
            return product,None,[],[],snapshot,complete
        raw,complete=pages(self.broker.fills_page,pid)
        fills=[normalize_fill(f)[1] for f in raw]
        # Include only attributable management reductions and previously verified bracket legs.
        reductions=[]
        for (detail,) in self.orders.db.execute("""SELECT a.detail FROM management_attempts a
            JOIN management_shadow s ON s.id=a.proposal_id
            WHERE a.symbol=? AND a.action IN ('reduce','close') AND a.status='verified'
            AND s.model IN (?,?) AND a.created>=?""",(SYMBOL,"gold-v2-controller.1",VERSION,int(seed["flat_observed_at"]))):
            item=json.loads(detail)
            r=self.broker.order(item["client_id"])
            if r.get("client_order_id")!=item["client_id"]:raise ValueError("reduction_identity_mismatch")
            reductions.append(r)
        reductions.extend(protective_receipts(self.broker,seed,fills,receipt,reductions,known_brackets(self.episodes,seed)))
        snapshot=self.manager.reader.observe(SYMBOL,pid)
        return product,receipt,fills,reductions,snapshot,complete
    def manage_cycle(self,report,history,seed):
        if not self.enabled:return status("disabled",execution_effect="none")
        verify_account(self.broker,self.expected)
        if seed.get("account_id")!=self.expected:raise ValueError("episode_account_mismatch")
        self.manager.reconcile_pending(SYMBOL)
        if self.pending_management():return status("unresolved_management")
        product,receipt,fills,reductions,snapshot,complete=self.collect(seed)
        if receipt is None:
            return status("entry_receipt_missing_recovery_checked")
        now=int(self.clock())
        state=self.episodes.record(seed["client_id"],receipt,fills,reductions,snapshot,now=now,complete=complete)
        if state["status"] in ("owned_open","closed","terminal_no_fill"):
            # Reconcile only the exact reserved client ID after verified episode replay.
            with self.orders.db:
                self.orders.db.execute("UPDATE orders SET status='acknowledged',detail=? WHERE client_id=? AND symbol=? AND status IN ('submitting','unknown')",
                    (json.dumps(receipt,allow_nan=False),seed["client_id"],SYMBOL))
        if state["status"]!="owned_open":return status(state["status"])
        first=state["first_full_bar_close"]
        bars=[b for b in history if b.ts>=first]
        packet=evaluate_episode(report,snapshot,product,seed,receipt,fills,reductions,
                                now=now,history=bars,complete=complete)
        if packet["status"]!="proposal_prepared":return status(packet["status"])
        if packet["proposal"]["action"]=="maintain":return status("holding")
        verify_account(self.broker,self.expected)
        ident=stage_management(self.orders.db,packet,now=int(self.clock()))
        if ident is None:return status("management_bucket_already_recorded")
        result=self.manager.execute(SYMBOL,ident,enabled=True)
        return status("management_dispatch",management_status=result.get("status"),
                      attempted=bool(result.get("attempted")))
    def cycle(self,report,history=()):
        if not self.enabled:return status("disabled",execution_effect="none")
        rows=outstanding(self.episodes)
        if len(rows)>1:return status("multiple_unresolved_episodes")
        if rows:return self.manage_cycle(report,history,rows[0][1])
        return self.entry_cycle(report)
