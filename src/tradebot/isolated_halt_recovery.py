"""Fail-closed automatic resumption of proven isolated DEMO no-order halts.

Never unhalt exposure, unverified execution, safety emergencies or missing
account evidence. Preserve each halt latch and a private write-once audit.
"""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import sqlite3
import stat
from uuid import uuid4

MARKETS = {
    "BTC": ("btc-isolated", "btc-auto-demo-halt", "fire-ops.sqlite"),
    "GOLD": ("gold-isolated", "gold-auto-demo-halt", "fire-xaut.sqlite"),
}
GOLD_NO_ORDER = frozenset((
    "risk_governor_failed", "market_quality_failed",
    "autonomous_invalid_wait", "provider_network_error", "provider_http_500",
))


def _proof(root, label):
    if label not in MARKETS or root.name != MARKETS[label][0]:
        return None
    path = root / MARKETS[label][2]
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with sqlite3.connect(path.absolute().as_uri()+"?mode=ro",
                             uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("SELECT name FROM sqlite_master WHERE "
                          "type='table' AND name='fire_entries'").fetchone() is None:
                return None
            rows = db.execute("SELECT press,status,result,created_at "
                "FROM fire_requests ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchall()
            if len(rows)!=1:
                return None
            press,status,raw,at=rows[0]
            if (status!="rejected_no_order" or type(press) is not str
                    or len(press)!=32 or any(c not in "0123456789abcdef" for c in press)):
                return None
            receipt=json.loads(raw)
            if (type(receipt) is not dict
                    or receipt.get("orders_submitted") is not False
                    or receipt.get("protection_verified") is not False
                    or receipt.get("broker_order_id")
                    or receipt.get("exit_order_ids")
                    or db.execute("SELECT 1 FROM fire_entries "
                                  "WHERE press=? LIMIT 1",(press,)).fetchone()):
                return None
            reason=receipt.get("reason_code")
            if label=="BTC":
                if reason=="risk_governor_failed":
                    from tradebot.btc_auto_review import evidence
                    if not (isinstance(evidence(root),dict)
                            and evidence(root).get("press")==press):
                        return None
                elif reason not in ("model_decision_failed","exchange_preflight_failed"):
                    return None
            elif reason not in GOLD_NO_ORDER:
                return None
            created=datetime.fromisoformat(at.replace("Z","+00:00"))
            if created.tzinfo is None:
                return None
            return {"press":press,"reason":reason,"created_us":int(created.timestamp()*1_000_000),
                    "receipt_sha256":sha256((press+"\0"+status+"\0"+raw).encode()).hexdigest()}
    except (sqlite3.Error,ValueError,TypeError,OSError,UnicodeError,OverflowError):
        return None


def recover_no_order_halt(root,label,*,candidate,receipt_check,active_probe,now=None):
    """Only recover a broker-proven flat, audited no-order incident.

    Read-only signed preflight is supplied by the existing isolated worker.
    No scheduling gate or order-risk rule is relaxed; next poll evaluates anew.
    """
    root=Path(root)
    if (label not in MARKETS or root.name!=MARKETS[label][0]
            or root.is_symlink() or not root.is_dir()):
        return {"status":"halted_pending_operator_review"}
    halt=root/MARKETS[label][1]
    if not halt.exists():
        return {"status":"no_halt"}
    try:
        h=halt.lstat()
        if (not stat.S_ISREG(h.st_mode) or stat.S_IMODE(h.st_mode)!=0o600
                or h.st_uid!=os.geteuid() or h.st_size!=0 or h.st_nlink!=1):
            return {"status":"halted_pending_operator_review"}
        time=now or datetime.now(timezone.utc)
        if time.tzinfo is None:
            return {"status":"halted_pending_operator_review"}
        proof=_proof(root,label)
        if proof is None:
            return {"status":"halted_pending_operator_review"}
        delay=time.timestamp()-proof["created_us"]/1_000_000
        if delay<300:
            return {"status":"halt_recovery_cooldown","remaining_seconds":int(300-delay)+1}
        if (receipt_check(root) is not True
                or candidate(root) is not True
                or active_probe(root) is not False):
            return {"status":"halt_recovery_broker_unavailable"}
        again=_proof(root,label)
        if again != proof or halt.lstat().st_ino!=h.st_ino:
            return {"status":"halt_recovery_receipt_changed"}
        folder=root/"halt-recovery-history"
        folder.mkdir(mode=0o700,exist_ok=True)
        if folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode)!=0o700:
            return {"status":"halted_pending_operator_review"}
        name=halt.name+"-"+uuid4().hex
        audit=folder/(name+".json")
        saved=folder/(name+".latch")
        record={"account":label,"source":"isolated_no_order_receipt",
                "press":proof["press"],"reason":proof["reason"],
                "receipt_sha256":proof["receipt_sha256"],
                "recovered_at_utc":time.astimezone(timezone.utc).isoformat(),
                "signed_isolated_preflight":True,"signed_flat_no_orders":True,
                "orders_submitted":False,"broker_mutations":False}
        fd=os.open(audit,os.O_WRONLY|os.O_CREAT|os.O_EXCL
                   |getattr(os,"O_NOFOLLOW",0),0o600)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                json.dump(record,stream,sort_keys=True)
                stream.write("\n");stream.flush();os.fsync(stream.fileno())
            os.replace(halt,saved)
            directory=os.open(folder,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
            try:os.fsync(directory)
            finally:os.close(directory)
            directory=os.open(root,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
            try:os.fsync(directory)
            finally:os.close(directory)
        except Exception:
            if halt.exists():
                audit.unlink(missing_ok=True)
            raise
        return {"status":"auto_recovered_verified_no_order",
                "reason":proof["reason"],"account":label}
    except (OSError,ValueError,TypeError,sqlite3.Error):
        return {"status":"halted_pending_operator_review"}

