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
