"""Owner-invoked, one-shot read-only connectivity bridge; no listener or credentials.
Caller supplies already authorized clients. Output is diagnostic metadata only.
"""
from pathlib import Path
from datetime import datetime,timezone
from tradebot.signed_account_context_v3 import read_signed_context,LABELS
from tradebot.m15_account_connectivity_v3 import project
from tradebot.model_wire_v3 import check_catalogue,MODEL_IDS
from tradebot.research_collector_v3 import atomic_json
from tradebot.delta import DEMO_API

FILENAME="owner-connectivity-bridge-v3.json"
MODE="owner_read_only_connectivity_bridge"

class AccountReader:
    """Fixed GET-only surface around a provisioned demo client."""
    base_url=DEMO_API
    allow_orders=False
    def __init__(self,client,symbol=None):
        if getattr(client,"base_url",None)!=DEMO_API or getattr(client,"allow_orders",None) is not False:
            raise ValueError("read_only_demo_required")
        if symbol is not None and symbol not in LABELS:
            raise ValueError("invalid_market")
        self._client=client; self._symbol=symbol; self._product=None
    def _verify_readonly(self):
        if getattr(self._client,"base_url",None)!=DEMO_API or getattr(self._client,"allow_orders",None) is not False:
            raise ValueError("read_only_demo_required")
    def _request(self,method,path,auth=False):
        self._verify_readonly()
        if method!="GET": raise ValueError("get_only")
        if self._symbol is None:
            allowed={"/v2/users/trading_preferences":True,"/v2/sub_accounts":True}
        else:
            allowed={"/v2/users/trading_preferences":True,"/v2/positions/margined":True,
                     "/v2/products/"+self._symbol:False}
            if self._product is not None:
                allowed[f"/v2/products/{self._product}/orders/leverage"]=True
        if path not in allowed or auth is not allowed[path]: raise ValueError("route_not_allowed")
        result=self._client._request(method,path,auth=auth)
        if self._symbol and path=="/v2/products/"+self._symbol:
            p=result["result"]
            if p.get("symbol")!=self._symbol or type(p.get("id")) is not int or p["id"]<=0:
                raise ValueError("wrong_product")
            self._product=p["id"]
        return result
    def open_orders(self):
        self._verify_readonly()
        if self._symbol is None: raise ValueError("parent_inventory_not_allowed")
        return self._client.open_orders()
    def wallet_balances(self):
        self._verify_readonly()
        if self._symbol is None: raise ValueError("parent_wallet_not_allowed")
        return self._client.wallet_balances()

def publish(root,*,children,parent,provider,clock=lambda:datetime.now(timezone.utc),accounts_only=False):
    root=Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError("invalid_output_directory")
    out={"mode":MODE,"markets":{},"catalogue_status":"not_provisioned",
         "execution_authorized":False,"paid_ai_requests":0,"orders_submitted":0}
    from tradebot.m27_direct_position_v3 import project as position_summary
    inventory={}
    catalogue={}
    if accounts_only and provider is not None: raise ValueError("accounts_only")
    if provider is not None:
        try: catalogue=check_catalogue(provider); out["catalogue_status"]="catalogue_returned"
        except Exception: out["catalogue_status"]="unavailable"
    for s,label in LABELS.items():
        item={"model_id":MODEL_IDS[s],"model_listed":catalogue.get(s,{}).get("available"),
              "account_status":"not_provisioned","account":None,"completion_verified":False}
        if parent is not None and children.get(s) is not None:
            phase=["client_validation"]
            try:
                a=read_signed_context(s,AccountReader(children[s],s),AccountReader(parent),clock=clock,stage=lambda x:phase.__setitem__(0,x))
                inventory[s]=a
                item["account"]=project(a,s);item["account_status"]="signed_read_only"
                item["account_observed_at"]=a["observed_at"]
            except Exception as exc:
                item["account_status"]="unavailable"
                item["failure_stage"]=phase[0]
                item["failure_code"]=failure_code(exc)
        out["markets"][s]=item
    out["checked_at"]=int(clock().timestamp())
    atomic_json(root/("owner-account-recheck-v3.json" if accounts_only else FILENAME),out)
    if not accounts_only:
        n=clock().timestamp()
        atomic_json(root/"m27-direct-position-v3.json",dict(
            mode="direct_signed_inventory_monitor_only",checked_at=int(n),
            markets={s:position_summary(s,inventory.get(s,{}),now=n) for s in LABELS},
            execution_authorized=False,orders_submitted=0,paid_ai_requests=0))

    return out

def read_report(root,*,now):
    import json,stat
    p=Path(root)/FILENAME
    try:
        st=p.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_size>64000: raise ValueError()
        with p.open("rb") as f: raw=f.read(64001)
        if len(raw)>64000: raise ValueError()
        r=json.loads(raw)
        t=r["checked_at"]
        if r["mode"]!=MODE or type(t) is not int or not 0<=now-t<=90 or r["execution_authorized"] is not False or r["paid_ai_requests"]!=0 or r["orders_submitted"]!=0: raise ValueError()
        if set(r["markets"])!=set(LABELS): raise ValueError()
        out={}
        for s in LABELS:
            a=r["markets"][s]
            if a["model_id"]!=MODEL_IDS[s] or a["completion_verified"] is not False or a["model_listed"] not in (None,True,False): raise ValueError()
            account=a["account"]
            verified=False
            if a["account_status"]=="signed_read_only":
                at=datetime.fromisoformat(a["account_observed_at"])
                verified=(at.tzinfo is not None and 0<=now-at.timestamp()<=60 and account["identity_verified"] is True
                    and account["signed_wallet_receipt_verified"] is True and account["execution_authorized"] is False
                    and account["paid_dispatch_authorized"] is False)
            out[s]={"account_evidence_fresh":verified,"model_listed":a["model_listed"],"completion_verified":False}
        return {"status":"fresh_local_report","markets":out,"execution_authorized":False}
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return {"status":"unavailable_or_stale","markets":{},"execution_authorized":False}

def failure_code(exc):
    from urllib.error import HTTPError
    allowed={"readonly_demo_required","read_only_demo_required","route_not_allowed","wrong_product","isolated_identity_unverified","wrong_leverage_product","invalid_amount","unexpected_exposure","inventory_may_be_truncated","order_inventory_unverified","unexpected_or_unverified_order_exposure","unexpected_order_state","account_snapshot_slow","signed_account_identity_unverified","signed_parent_readonly_demo_required","signed_parent_identity_unverified","signed_parent_must_be_distinct","signed_parent_roster_unverified","signed_parent_roster_identity_conflict","signed_child_not_in_parent_roster","signed_parent_margin_mode_unverified","signed_child_parent_margin_mode_conflict","signed_subaccount_market_label_mismatch","signed_parent_subaccount_evidence_unavailable","broker_authentication_failed","broker_equity_unavailable","broker_equity_rejected"}
    if len(exc.args)==1 and isinstance(exc.args[0],str) and exc.args[0] in allowed: return exc.args[0]
    cause=exc.__cause__
    if isinstance(cause,HTTPError) and cause.code in (400,401,403,404,429,500,503): return "http_"+str(cause.code)
    if isinstance(exc,KeyError): return "required_field_missing"
    if isinstance(exc,ValueError): return "validation_failed"
    if isinstance(exc,TypeError): return "unexpected_schema"
    return "read_unavailable"
