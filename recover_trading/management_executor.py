"""Demo position management executor. Explicit activation; no replay of mutations."""
import hashlib,json,sqlite3,time
from .broker import DeltaDemo,DEMO_API,error_detail
from .engine import OrderIntent
from .execution import product_for
from .bracket_repair import BracketRepair
from .bracket_contract import fixture_payload,verify_fixture
from .lifecycle import pages,normalize_fill
from .management_lifecycle import plan,current_match,reconcile
from .position_preview import observe
from .performance import dec

VERSION="management-executor-v1"

def identity(snapshot):
    pos=snapshot["positions"][0]
    created=pos.get("created_at")
    if not isinstance(created,str) or not created:return None
    if snapshot.get("active_orders_complete") is not True or "active_orders" in (snapshot.get("errors") or {}):return None
    orders=snapshot.get("active_orders")
    if not isinstance(orders,list):return None
    legs=[]
    for o in orders:
        if not isinstance(o,dict) or o.get("id") is None:return None
        legs.append([str(o["id"]),o.get("stop_order_type"),str(dec(o.get("stop_price"))),str(dec(o.get("unfilled_size")))])
    if len({o[0] for o in legs})!=len(legs):return None
    return {"created_at":created,"legs":sorted(legs)}

class ManagementExecutor:
    def __init__(self,broker,journal):
        if not isinstance(broker,DeltaDemo) or DEMO_API!="https://cdn-ind.testnet.deltaex.org":raise ValueError("Demo client required")
        self.broker=broker;self.db=journal.db;self.reader=BracketRepair(broker,journal)
        with self.db:self.db.execute("""CREATE TABLE IF NOT EXISTS management_attempts (
            proposal_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,created INTEGER NOT NULL,
            action TEXT NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL)""")

    def execute(self,symbol,ident,*,enabled=False):
        def result(status,**kw):return {"version":VERSION,"status":status,"attempted":False,**kw}
        if not enabled:return result("execution_disabled")
        row=self.db.execute("SELECT context,result FROM management_shadow WHERE id=? AND symbol=? AND status='proposed'",(ident,symbol)).fetchone()
        if not row:return result("proposal_unavailable")
        prior=self.db.execute("SELECT status FROM management_attempts WHERE proposal_id=?",(ident,)).fetchone()
        if prior:return result("already_recorded",previous_status=prior[0])
        # Never submit a second management mutation while a previous outcome is ambiguous.
        pending=self.db.execute("SELECT proposal_id FROM management_attempts WHERE symbol=? AND status IN ('attempting','outcome_unverified','partial_result_unverified') LIMIT 1",(symbol,)).fetchone()
        if pending:return result("previous_management_outcome_unverified")
        try:
            c=json.loads(row[0]);p=plan(c,json.loads(row[1])["proposal"]);action=p["action"]
            if p["symbol"]!=symbol:return result("proposal_symbol_mismatch")
            if action=="maintain":return result("no_mutation_requested")
            product=product_for(self.broker,symbol);pid=product["id"]
            if pid!=p["product_id"] or dec(product["tick_size"])!=dec(c["product"]["tick_size"]):return result("product_changed")
            before=self.reader.observe(symbol,pid)
            if current_match(p,before,int(time.time()))!="matching_observation_not_execution_authority":return result("current_observation_changed")
            ident_before=identity(before)
            if ident_before is None or c.get("execution_identity")!=ident_before:return result("position_or_order_identity_changed")
            q=p["before_size"];cid=hashlib.sha256(("management:"+ident).encode()).hexdigest()[:32]
            payload=None;leg_id=None
            if action in ("update_bracket","repair_bracket"):
                d=p["desired_triggers"];sl,tp=dec(d["stop_loss"]),dec(d["take_profit"])
                t=self.broker.ticker(symbol);ts=t.get("timestamp")
                if t.get("symbol")!=symbol or t.get("product_id")!=pid or type(ts) is not int or not 0<=time.time_ns()//1000-ts<=30_000_000:return result("ticker_unverified")
                payload=fixture_payload(pid,q,t.get("mark_price"),sl,tp,product["tick_size"])
                if action=="update_bracket":
                    orders=before["active_orders"]
                    if len(orders)!=2 or any(o.get("stop_trigger_method")!="mark_price" for o in orders):return result("existing_orders_unverified")
                    legs={o["stop_order_type"]:o for o in orders}
                    a,b=legs["stop_loss_order"],legs["take_profit_order"]
                    if dec(b["stop_price"])!=tp:return result("take_profit_amendment_not_verified")
                    if dec(a["stop_price"])==sl:return result("no_change_requested")
                    leg_id=a["id"]
                    payload={"id":leg_id,"product_id":pid,"size":abs(q),"stop_price":format(sl,"f")}
            elif action not in ("reduce","close"):return result("unsupported_action")
            # Position identity is checked again immediately before durable reservation.
            latest=self.reader.observe(symbol,pid)
            if identity(latest)!=ident_before or current_match(p,latest,int(time.time()))!="matching_observation_not_execution_authority":return result("position_or_order_identity_changed")
        except Exception as e:return result("preparation_error",**error_detail(e))
        detail={"plan":p,"identity":ident_before,"client_id":cid,"payload":payload}
        try:
            with self.db:self.db.execute("INSERT INTO management_attempts VALUES (?,?,?,?,?,?)",(ident,symbol,int(time.time()),action,"attempting",json.dumps(detail)))
        except sqlite3.IntegrityError:return result("already_recorded")
        receipt=None
        try:
            if action=="repair_bracket":receipt=self.broker._request("POST","/v2/orders/bracket",payload=payload,auth=True)
            elif action=="update_bracket":receipt=self.broker._request("PUT","/v2/orders",payload=payload,auth=True)
            else:receipt=self.broker.submit(OrderIntent(pid,"sell" if q>0 else "buy",p["requested_reduction"],True),cid)
            detail["response"]="acknowledged"
        except Exception as e:detail["response"]="unknown";detail["error"]=error_detail(e)
        # Persist the response before verification. A crash leaves a durable ambiguous attempt.
        if isinstance(receipt,dict):detail["receipt"]={k:receipt[k] for k in ("id","client_order_id","product_id","state","size","unfilled_size","reduce_only","stop_price","success") if k in receipt}
        with self.db:self.db.execute("UPDATE management_attempts SET detail=? WHERE proposal_id=?",(json.dumps(detail),ident))
        status,detail=self._verify(symbol,detail)
        with self.db:self.db.execute("UPDATE management_attempts SET status=?,detail=? WHERE proposal_id=?",(status,json.dumps(detail),ident))
        return {"version":VERSION,"status":status,"action":action,"attempted":True}

    def _verify(self,symbol,detail):
        """Read-only re-observation; never resubmit or amend an order."""
        p=detail["plan"];action=p["action"];pid=p["product_id"];q=p["before_size"]
        ident_before=detail["identity"];cid=detail["client_id"]
        detail={**detail,"last_reconciled":int(time.time())}
        detail.pop("verification_error",None)
        status="outcome_unverified"
        try:
            after=self.reader.observe(symbol,pid)
            view=observe(after,symbol,int(time.time()))
            if view["position_state"] in ("long","short") and (after["positions"][0].get("created_at")!=ident_before["created_at"] or dec(view.get("entry_price"))!=dec(p["entry_price"])):
                return "outcome_unverified",{**detail,"evidence":"position_lineage_changed","last_reconciled":int(time.time())}
            if action in ("repair_bracket","update_bracket"):
                d=p["desired_triggers"]
                evidence=verify_fixture(after,symbol,int(time.time()),q,d["stop_loss"],d["take_profit"])
                detail["evidence"]=evidence
                if evidence=="matching_triggers_observed" and identity(after) is not None and identity(after)["created_at"]==ident_before["created_at"] and all(o.get("stop_trigger_method")=="mark_price" for o in after["active_orders"]):
                    if action=="repair_bracket" or {str(o["id"]) for o in after["active_orders"]}=={x[0] for x in ident_before["legs"]}:status="verified"
            else:
                order=self.broker.order(cid)
                if order.get("client_order_id")!=cid:raise ValueError("order identity")
                raw,complete=pages(self.broker.fills_page,pid)
                evidence=reconcile(p,after,int(time.time()),order=order,fills=[normalize_fill(f)[1] for f in raw],complete_fills=complete)
                detail["evidence"]=evidence
                if evidence["status"] in ("full_close_observed","partial_close_observed") and evidence["target_size_observed"]:status="verified"
                elif evidence["status"]=="no_fill_observed" and identity(after)==ident_before:status="terminal_no_fill"
                elif evidence["status"] in ("full_close_observed","partial_close_observed","flat_residual_orders_unverified","reduction_bracket_unverified"):status="partial_result_unverified"
            detail["observed_size"]=view.get("size");detail["bracket_state"]=view.get("bracket_state")
        except Exception as e:detail["verification_error"]=error_detail(e)
        return status,detail

    def reconcile_pending(self,symbol):
        """Revisit ambiguous attempts using only exchange reads and journal updates."""
        counts={"checked":0,"resolved":0,"unresolved":0,"errors":0}
        rows=self.db.execute("SELECT proposal_id,status,detail FROM management_attempts WHERE symbol=? AND status IN ('attempting','outcome_unverified','partial_result_unverified') ORDER BY created LIMIT 3",(symbol,)).fetchall()
        for ident,old,raw in rows:
            counts["checked"]+=1
            try:
                detail=json.loads(raw)
                if detail["plan"]["symbol"]!=symbol:raise ValueError("journal_symbol")
                status,detail=self._verify(symbol,detail)
                with self.db:self.db.execute("UPDATE management_attempts SET status=?,detail=? WHERE proposal_id=? AND status=?",(status,json.dumps(detail),ident,old))
                if status in ("verified","terminal_no_fill"):counts["resolved"]+=1
                else:counts["unresolved"]+=1
            except Exception:counts["errors"]+=1
        return {"version":VERSION,**counts,"execution_effect":"none"}
