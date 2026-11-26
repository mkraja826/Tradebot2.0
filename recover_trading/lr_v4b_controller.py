"""BTC LR-V4-B cycle routing and sizing contract; activation separate.

The controller is called by one existing market worker, not a second trader.
It holds ownership across ambiguous broker outcomes. No historical signal
is used to enter a position.
"""
import json
import sqlite3
import time
from contextlib import closing
from .execution import account_context
from .lr_v4b_attribution import Attribution
from .lr_v4b_execution import submit
from .lr_v4b_management import LRManager
from .lr_v4b_archive import connect
from .performance import dec

SIZING_SYSTEM = """Size a BTCUSD demo trade using the supplied wallet and product.
The strategy sets direction and bracket; do not invent prices or change direction.
Return JSON only: symbol BTCUSD, action trade or no_trade, reason.
For trade include side (copy signal side), size (positive integer contracts),
leverage exactly 20, capital_allocation (intended initial margin in settlement
asset, excluding fees). Use actual available margin and contract specifications.
Do not claim order execution."""


class Controller:
    def __init__(self,entry_executor,management_executor,provider,model,market_path):
        self.entry=entry_executor
        self.manager=LRManager(management_executor)
        self.provider=provider
        self.model=model
        self.market_path=market_path
        self.db=entry_executor.journal.db
        Attribution(self.db)
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS lr_v4b_sizing (
                signal_time INTEGER NOT NULL, burst_time INTEGER NOT NULL, side TEXT NOT NULL,
                created INTEGER NOT NULL, status TEXT NOT NULL, detail TEXT,
                PRIMARY KEY(signal_time,burst_time,side))''')

    def outstanding(self):
        return self.db.execute("""SELECT l.client_id,l.state,o.status FROM lr_v4b_entries l
            LEFT JOIN orders o ON o.client_id=l.client_id
            WHERE l.state NOT IN ('finished','preparation_failed')""").fetchall()

    def release_flat(self,snapshot):
        """Release ownership only after observed flat and terminal entry order."""
        if (snapshot.get("positions")!=[] or snapshot.get("active_orders")!=[]
                or snapshot.get("active_orders_complete") is not True
                or any(k in (snapshot.get("errors") or {}) for k in ("positions","active_orders"))):
            return
        for cid,state,order_state in self.outstanding():
            if order_state is None and state=="reserved":
                # The same serial worker has not entered the executor journal.
                terminal=True
            elif order_state=="preparation_failed":
                terminal=True
            elif order_state=="acknowledged":
                try:
                    row=self.entry.broker.order(cid)
                    q,remaining=dec(row.get("size")),dec(row.get("unfilled_size"))
                    terminal=(row.get("client_order_id")==cid and q is not None and q>0
                              and remaining is not None and 0<=remaining<=q
                              and row.get("state") in ("closed","cancelled","canceled")
                              and (row.get("state")!="closed" or remaining==0))
                except Exception:
                    terminal=False
            else:
                terminal=False
            if terminal:
                with self.db:self.db.execute("UPDATE lr_v4b_entries SET state='finished' WHERE client_id=?",(cid,))

    def candles(self,now):
        cutoff=now//60*60
        with closing(connect(self.market_path)) as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM samples WHERE symbol='BTCUSD' AND series='candle:1m' AND stamp>=? AND stamp<? ORDER BY stamp",
                (cutoff-14400,cutoff))]

    def manage(self,report,snapshot):
        self.release_flat(snapshot)
        if not self.outstanding():
            return None
        try:
            now=int(time.time())
            return self.manager.run(report,self.candles(now),enabled=True,now=now)
        except Exception as exc:
            return {"status":"lr_management_error","error":type(exc).__name__,"attempted":False}

    def enter(self,shadow,snapshot):
        signal=(shadow or {}).get("recent_signal")
        if not signal or self.outstanding():
            return None
        if (snapshot.get("positions")!=[] or snapshot.get("active_orders")!=[]
                or snapshot.get("active_orders_complete") is not True
                or any(k in (snapshot.get("errors") or {}) for k in ("positions","active_orders"))):
            return None
        now=int(time.time())
        if not 0<=now-signal["signal_time"]<60:
            return {"status":"lr_signal_expired","ai_calls":0}
        if shadow.get("status")!="observed" or signal.get("version")!="lr-v4b" or signal.get("symbol")!="BTCUSD":
            return {"status":"lr_signal_unverified","ai_calls":0}
        key=(signal["signal_time"],signal["burst_time"],signal["side"])
        try:
            with self.db:
                self.db.execute("INSERT INTO lr_v4b_sizing VALUES(?,?,?,?,'requested',NULL)",(*key,now))
        except sqlite3.IntegrityError:
            return {"status":"lr_sizing_already_requested","ai_calls":0}
        calls=0
        try:
            account=account_context(self.entry.broker,"BTCUSD")
            if not 0<=int(time.time())-signal["signal_time"]<60:
                result={"status":"stale_signal","execution_effect":"none"}
            else:
                calls=1
                sizing=self.provider._propose(self.model,{"symbol":"BTCUSD","signal":signal,
                     "demo_account":account},SIZING_SYSTEM)
                result=submit(signal,sizing,self.entry,enabled=True)
        except Exception as exc:
            result={"status":"lr_entry_error","error":type(exc).__name__}
        with self.db:
            self.db.execute("UPDATE lr_v4b_sizing SET status=?,detail=? WHERE signal_time=? AND burst_time=? AND side=?",
                            (result["status"],json.dumps({"ai_calls":calls,"status":result["status"],"client_id":result.get("client_id")}),*key))
        return {"decision":{"status":"lr_v4b_entry","ai_calls":calls},"execution":result}
