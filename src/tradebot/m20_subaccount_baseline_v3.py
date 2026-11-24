"""Immutable forward diagnostic baseline; never replaces loss-limit history."""
import os,json,stat,hashlib,tempfile
from pathlib import Path
from datetime import datetime
from time import time
from decimal import Decimal
from tradebot.signed_account_context_v3 import LABELS
SOURCE="m20-subaccount-evidence-v3.json"
TARGET="m20-subaccount-baseline-v3.json"

def read_private(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or s.st_mode&0o077 or s.st_nlink!=1 or not 0<s.st_size<=64000:
            raise ValueError("private_report_required")
        raw=f.read(64001)
    if len(raw)>64000:raise ValueError("oversized_report")
    return raw

def project(raw,now):
    r=json.loads(raw)
    if r.get("mode")!="subaccount_evidence_only" or r.get("parent_equity_included") is not False or r.get("execution_authorized") is not False or r.get("orders_submitted")!=0 or r.get("paid_ai_requests")!=0:
        raise ValueError("invalid_source")
    if type(r["checked_at"]) is not int or not 0<=now-r["checked_at"]<=90 or set(r["markets"])!=set(LABELS):
        raise ValueError("stale_or_incomplete")
    out={"mode":"forward_subaccount_baseline_diagnostic_only","created_at":int(now),
         "source_sha256":hashlib.sha256(raw).hexdigest(),"parent_equity_included":False,
         "historical_checkpoint_replaced":False,"execution_authorized":False,
         "orders_submitted":0,"paid_ai_requests":0,"markets":{}}
    for s,label in LABELS.items():
        a=r["markets"][s];at=datetime.fromisoformat(a["window_end"])
        if at.tzinfo is None or not 0<=now-at.timestamp()<=90 or a["status"]!="complete_window" or a["subaccount"]!=label or a["signed_identity_verified"] is not True or a["signed_wallet_receipt_verified"] is not True or a["counts"]["unclassified"]!=0:
            raise ValueError("invalid_market_evidence")
        equity=Decimal(a["snapshot_equity_usd"])
        if not equity.is_finite() or equity<=0:raise ValueError("invalid_equity")
        out["markets"][s]={"subaccount":label,"observed_at":at.isoformat(),"opening_equity_usd":str(equity),
            "scope":"prospective_diagnostic_only","historical_loss_status":"not_reconciled",
            "transfer_adjusted_return_verified":False,"execution_authorized":False}
    return out

def create(root,*,clock=time):
    root=Path(root);p=root/TARGET
    if os.path.lexists(p):raise FileExistsError("baseline_already_exists")
    r=project(read_private(root/SOURCE),clock())
    fd,tmp=tempfile.mkstemp(prefix=".baseline-",dir=root)
    try:
        with os.fdopen(fd,"w") as f:
            os.fchmod(f.fileno(),0o600);json.dump(r,f,sort_keys=True,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.link(tmp,p)
        d=os.open(root,os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:os.unlink(tmp)
    return r
