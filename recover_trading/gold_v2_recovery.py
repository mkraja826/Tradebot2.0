"""Read-only exchange recovery helpers. Never resend an ambiguous order."""
import json
from urllib.parse import quote
from .broker import BrokerError
from .gold_v2_episode import d,timestamp
from .position_preview import observe

VERSION="gold-v2-recovery.1"
SYMBOL="XAUTUSD"

def known_brackets(episodes,seed):
    """Only bracket IDs from previously verified, owned episode snapshots."""
    rows=episodes.db.execute("""SELECT observed_at,result FROM gold_v2_episode_observations
        WHERE client_id=? ORDER BY observed_at""",(seed["client_id"],))
    known={}
    for at,raw in rows:
        result=json.loads(raw)
        if result.get("status")!="owned_open":continue
        for oid,kind,trigger,remaining in result["identity"]["legs"]:
            if kind not in ("stop_loss_order","take_profit_order"):continue
            old=known.get(oid)
            if old and old["kind"]!=kind:raise ValueError("bracket_identity_conflict")
            known[oid]={"kind":kind,"first_seen":old["first_seen"] if old else at}
    return known

def protective_receipts(broker,seed,fills,entry_receipt,reductions,known):
    """Attribute observed fills to previously verified protective legs only."""
    pid=seed["product_id"];side="sell" if seed["side"]=="buy" else "buy"
    accounted={str(entry_receipt["id"])}|{str(r["id"]) for r in reductions}
    by_order={}
    for f in fills:
        if timestamp(f["created_at"])<seed["flat_observed_at"]:continue
        oid=str(f["order_id"])
        if oid not in accounted:by_order.setdefault(oid,[]).append(f)
    found=[]
    for oid,rows in sorted(by_order.items()):
        prior=known.get(oid)
        if prior is None:continue
        # Only numeric exchange IDs, not arbitrary paths.
        if not oid.isdigit() or int(oid)<=0:raise ValueError("invalid_order_id")
        if any(timestamp(f["created_at"])<=prior["first_seen"] for f in rows):continue
        r=broker._request("GET","/v2/orders/"+quote(oid,safe=""),auth=True)
        if (str(r.get("id"))!=oid or str(r.get("product_id"))!=str(pid)
            or r.get("side")!=side or r.get("reduce_only") is not True
            or r.get("bracket_order") is not True or r.get("stop_order_type")!=prior["kind"]
            or r.get("stop_trigger_method")!="mark_price"
            or r.get("state") not in ("closed","cancelled","canceled")):
            continue
        q,left=d(r["size"]),d(r["unfilled_size"])
        if not 0<=left<=q or (r["state"]=="closed" and left!=0):continue
        if sum(d(f["size"]) for f in rows)!=q-left:continue
        found.append(r)
    return found

def local_no_submission(orders,seed):
    """Only proven pre-dispatch states qualify; missing exchange order alone does not."""
    row=orders.db.execute("SELECT symbol,status,intent FROM orders WHERE client_id=?",
                          (seed["client_id"],)).fetchone()
    if row is None:return "no_local_order_reservation"
    symbol,state,raw=row
    intent=json.loads(raw)
    if symbol!=SYMBOL or intent.get("product_id")!=seed["product_id"] or intent.get("side")!=seed["side"] or d(intent["size"])!=d(seed["size"]):
        return None
    if state=="preparation_failed":return "local_preparation_failed"
    return None

def verify_no_submission(seed,fills,snapshot,*,now,complete,local_reason,error):
    # Requires intact local journal, exclusive worker ownership, and explicit
    # exchange order_not_found, not generic HTTP/transport failure.
    if local_reason not in ("no_local_order_reservation","local_preparation_failed"):
        return None
    if not isinstance(error,BrokerError) or error.exchange_code!="order_not_found":
        return None
    if complete is not True:return None
    v=observe(snapshot,SYMBOL,now)
    if v["position_state"]!="flat" or v["bracket_state"]!="no_orders_observed":return None
    if any(timestamp(f["created_at"])>=seed["flat_observed_at"] for f in fills):return None
    if not 120<=now-seed["flat_observed_at"]:return None
    return {"version":VERSION,"symbol":SYMBOL,"status":"terminal_no_submission",
            "execution_effect":"none","reason":local_reason,"exchange_code":"order_not_found"}

def persist_no_submission(episodes,seed,result,*,now):
    """Append a distinct terminal recovery observation; never fabricate a fill."""
    if result.get("status")!="terminal_no_submission":raise ValueError("invalid_recovery_result")
    cid=seed["client_id"]
    with episodes.db:
        episodes.db.execute("BEGIN IMMEDIATE")
        row=episodes.db.execute("SELECT seed FROM gold_v2_episodes WHERE client_id=?",(cid,)).fetchone()
        if row is None or json.loads(row[0])!=seed:raise ValueError("episode_seed_mismatch")
        old=episodes.db.execute("""SELECT observed_at,result FROM gold_v2_episode_observations
            WHERE client_id=? ORDER BY observed_at DESC LIMIT 1""",(cid,)).fetchone()
        if old and (now<=old[0] or json.loads(old[1])["status"] in
                    ("owned_open","closed","terminal_no_fill","terminal_no_submission")):
            raise ValueError("invalid_recovery_transition")
        # Never abandon an episode that was previously observed as owned.
        for (raw,) in episodes.db.execute("SELECT result FROM gold_v2_episode_observations WHERE client_id=?",(cid,)):
            if json.loads(raw)["status"]=="owned_open":raise ValueError("previously_owned")
        raw=json.dumps(result,sort_keys=True,allow_nan=False)
        episodes.db.execute("INSERT INTO gold_v2_episode_observations VALUES (?,?,?,?)",
                            (cid,now,raw,raw))
    return result


def synchronize_terminal_entries(orders,episodes,expected_account):
    """Repair a crash between terminal episode commit and entry-journal update.

    Replay persisted exchange evidence, not merely the terminal status label.
    Never query or mutate exchange orders; never clear unrelated reservations.
    """
    from .gold_v2_episode import reconcile,client_id
    repaired=0
    unresolved=orders.db.execute("""SELECT client_id,symbol,intent,status FROM orders
        WHERE status IN ('submitting','unknown') AND symbol=?""",(SYMBOL,)).fetchall()
    for cid,symbol,raw,prior in unresolved:
        row=episodes.db.execute("""SELECT e.seed,o.observed_at,o.evidence,o.result
            FROM gold_v2_episodes e JOIN gold_v2_episode_observations o
            ON e.client_id=o.client_id WHERE e.client_id=?
            ORDER BY o.observed_at DESC LIMIT 1""",(cid,)).fetchone()
        if row is None:continue
        try:
            seed,at,evidence,saved=json.loads(row[0]),row[1],json.loads(row[2]),json.loads(row[3])
            if (saved.get("status") not in ("closed","terminal_no_fill")
                or seed.get("account_id")!=str(expected_account) or seed.get("symbol")!=SYMBOL
                or seed.get("client_id")!=cid or client_id(seed["signal_boundary"])!=cid):
                continue
            intent=json.loads(raw)
            if (intent.get("product_id")!=seed["product_id"] or intent.get("side")!=seed["side"]
                or d(intent["size"])!=d(seed["size"]) or intent.get("leverage")!=20
                or intent.get("reduce_only",False) is not False or d(intent["stop_loss"])!=d(seed["stop_loss"]) or d(intent["take_profit"])!=d(seed["take_profit"])):
                continue
            receipt=evidence["receipt"]
            replay=reconcile(seed,receipt,evidence["fills"],evidence["reductions"],
                evidence["snapshot"],now=at,complete=evidence["complete"])
            if replay!=saved:continue
            detail=json.dumps(receipt,allow_nan=False)
        except (KeyError,TypeError,ValueError,ArithmeticError,AttributeError):
            continue
        with orders.db:
            repaired+=orders.db.execute("""UPDATE orders SET status='acknowledged',detail=?
                WHERE client_id=? AND symbol=? AND status=? AND intent=?""",
                (detail,cid,SYMBOL,prior,raw)).rowcount
    return repaired


def early_exit_diagnostic(broker,seed,entry,fills,snapshot,*,now,complete):
    """Classify a possible early protective exit without granting ownership.

    Exact price/size/account/type matches are circumstantial, not parent
    linkage. Never feed the candidate receipt into authorized reductions.
    """
    from .gold_v2_episode import reconcile
    def out(s,**kw):return {"status":s,"execution_effect":"none","attribution_verified":False,**kw}
    if complete is not True:return out("incomplete_fills")
    try:
        v=observe(snapshot,SYMBOL,now)
        if v["position_state"]!="flat" or v["bracket_state"]!="no_orders_observed":
            return out("not_flat")
        if str(entry.get("user_id"))!=str(seed["account_id"]):return out("entry_account_unverified")
        if entry.get("client_order_id")!=seed["client_id"] or entry.get("id") is None:
            return out("entry_identity_unverified")
        if d(entry["bracket_stop_loss_price"])!=d(seed["stop_loss"]) or d(entry["bracket_take_profit_price"])!=d(seed["take_profit"]):
            return out("entry_bracket_mismatch")
        ids={str(f["order_id"]) for f in fills if timestamp(f["created_at"])>=seed["flat_observed_at"]}
        ids.discard(str(entry["id"]))
        if len(ids)!=1:return out("ambiguous_exit_orders")
        oid=ids.pop()
        if not oid.isdigit() or int(oid)<=0:return out("invalid_exit_id")
        r=broker._request("GET","/v2/orders/"+quote(oid,safe=""),auth=True)
        kind=r.get("stop_order_type")
        key={"stop_loss_order":"stop_loss","take_profit_order":"take_profit"}.get(kind)
        if (key is None or str(r.get("id"))!=oid or str(r.get("user_id"))!=str(seed["account_id"])
            or r.get("bracket_order") is not True or r.get("stop_trigger_method")!="mark_price"
            or d(r["stop_price"])!=d(seed[key])):
            return out("protective_evidence_mismatch")
        replay=reconcile(seed,entry,fills,[r],snapshot,now=now,complete=complete)
        if replay["status"]!="closed":return out("fill_chain_unverified")
        return out("possible_early_protective_exit",protective_kind=kind,
                   required_evidence="verified_parent_child_link_or_previously_observed_leg")
    except (KeyError,ValueError,TypeError,ArithmeticError,AttributeError,BrokerError):
        return out("diagnostic_unavailable")
