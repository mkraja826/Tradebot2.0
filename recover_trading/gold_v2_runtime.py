"""Dedicated Gold V2 demo runtime. No automatic activation.

The operator must verify that the legacy Gold writer has stopped. The local
account lock is cooperative and cannot exclude an older process or another VM.
"""
import argparse
from contextlib import contextmanager,ExitStack
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import threading
from .broker import DeltaDemo
from .engine import Journal
from .gold_v2_episode import EpisodeJournal
from .gold_v2_controller import Controller,outstanding,verify_account
from .gold_v2_worker import Worker,account_snapshot
from .gold_v2_public_feeds import PublicFeeds
from .gold_v2_fundamentals import collect_external
from .gold_v2_entry_adapter import positive
from tradebot.market_data_v3 import public_client

VERSION="gold-v2-runtime.1"
LOCK_ROOT=Path("/var/lib/recover-trading/gold-v2-locks")
DATA_ROOT=Path("/var/lib/recover-trading/gold-v2-execution")

def account_id(value):
    s=str(value)
    if not s.isascii() or not s.isdigit() or int(s)<=0 or str(int(s))!=s:
        raise ValueError("invalid_account_id")
    return s

def config(env):
    gold,btc,main=[account_id(env.get(k,"")) for k in
        ("RECOVER_GOLD_V2_ACCOUNT","RECOVER_BTC_ACCOUNT","RECOVER_MAIN_ACCOUNT")]
    if len({gold,btc,main})!=3 or gold=="26679287":
        raise ValueError("account_identity_overlap")
    key,secret,bkey,bsecret=[env.get(k) for k in ("RECOVER_GOLD_DEMO_KEY","RECOVER_GOLD_DEMO_SECRET",
        "RECOVER_BTC_DEMO_KEY","RECOVER_BTC_DEMO_SECRET")]
    if not all((key,secret,bkey,bsecret)) or key==bkey:
        raise ValueError("distinct_demo_credentials_required")
    allocation=positive(env.get("RECOVER_GOLD_V2_ALLOCATION"))
    if allocation>1:raise ValueError("invalid_allocation")
    return gold,btc,main,key,secret,bkey,bsecret,allocation

@contextmanager
def owner_lock(root,account):
    account=account_id(account)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    # Never unlink the lock file: a second process could lock a new inode.
    with (root/("gold-"+account+".lock")).open("a") as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield

def bind_journal(orders,episodes,account):
    """Refuse accidental reuse of another account's dedicated execution data."""
    account=account_id(account)
    for db,table in ((orders.db,"orders"),(episodes.db,"gold_v2_episodes")):
        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS gold_v2_runtime_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), account_id TEXT NOT NULL)")
            row=db.execute("SELECT account_id FROM gold_v2_runtime_owner WHERE singleton=1").fetchone()
            if row is None:
                if db.execute("SELECT 1 FROM "+table+" LIMIT 1").fetchone():
                    raise ValueError("unbound_nonempty_execution_journal")
                db.execute("INSERT INTO gold_v2_runtime_owner VALUES(1,?)",(account,))
            elif row[0]!=account:raise ValueError("journal_account_mismatch")

def verify_start(broker,btc_broker,gold,btc,main,episodes):
    if len({account_id(x) for x in (gold,btc,main)})!=3:
        raise ValueError("account_identity_overlap")
    verify_account(broker,gold)
    wallet,=[w for w in btc_broker.wallet()["result"] if w.get("asset_symbol")=="USD"]
    if str(wallet.get("user_id"))!=btc:raise ValueError("btc_wallet_mismatch")
    view=account_snapshot(broker,gold)
    rows=outstanding(episodes)
    if len(rows)>1 or any(seed.get("account_id")!=gold for _,seed in rows):
        raise ValueError("episode_account_or_count_unverified")
    if not rows and (view["position_state"]!="flat" or view["bracket_state"]!="no_orders_observed"):
        raise ValueError("legacy_or_unowned_position")
    return {"status":"read_checks_passed","symbol":"XAUTUSD","position_state":view["position_state"],
            "bracket_state":view["bracket_state"],"outstanding_episodes":len(rows),
            "execution_effect":"none","legacy_writer_exclusion":"operator_assertion_only"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight",action="store_true")
    mode.add_argument("--execute-demo",action="store_true")
    p.add_argument("--interval",type=float,default=60)
    p.add_argument("--legacy-gold-stopped",action="store_true",
                   help="Explicit local operator assertion; not proof of exclusive exchange ownership")
    args=p.parse_args()
    if not math.isfinite(args.interval) or args.interval<=0:p.error("invalid interval")
    if args.execute_demo and not args.legacy_gold_stopped:p.error("Gold-only handoff assertion required")
    try:
        gold,btc,main_id,key,secret,bkey,bsecret,allocation=config(os.environ)
        broker=DeltaDemo(key,secret);btc_broker=DeltaDemo(bkey,bsecret)
        with owner_lock(LOCK_ROOT,gold),ExitStack() as stack:
            root=DATA_ROOT
            root.mkdir(parents=True,exist_ok=True)
            orders=Journal(root/"orders.sqlite");stack.callback(orders.close)
            episodes=EpisodeJournal(root/"episodes.sqlite");stack.callback(episodes.close)
            bind_journal(orders,episodes,gold)
            state=verify_start(broker,btc_broker,gold,btc,main_id,episodes)
            print(json.dumps(state),flush=True)
            if args.preflight:return 0
            # Explicitly separate from the shadow CLI, which cannot submit.
            controller=Controller(broker,orders,episodes,expected_account=gold,
                                  allocation_fraction=allocation,enabled=True)
            worker=Worker(root,public_client(),broker=broker,expected_account=gold,
                          external=collect_external,public_feeds=PublicFeeds(),controller=controller)
            stop=threading.Event()
            for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
            worker.run(stop,args.interval)
            return 0
    except Exception as exc:
        print(json.dumps({"version":VERSION,"status":"runtime_stopped","error":type(exc).__name__,
                          "execution_effect":"unknown_if_dispatch_previously_enabled" if args.execute_demo else "none"}),flush=True)
        return 1

if __name__=="__main__":raise SystemExit(main())
