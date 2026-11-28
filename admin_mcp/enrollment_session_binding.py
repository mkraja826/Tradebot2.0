"""Session-bound enrollment challenges for the trusted provisioning gateway."""
import secrets
import time
from provisioning_session import digest
from enrollment_controller import check_scope
from enrollment_provisioning import encode
import hashlib

def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS bound_enrollment (session_digest BLOB PRIMARY KEY, challenge BLOB UNIQUE NOT NULL, operator TEXT NOT NULL, expires INTEGER NOT NULL)")
    db.commit()

def options(db, policy, token, operator):
    check_scope(operator, policy)
    key = digest(token)
    if db.in_transaction:
        raise RuntimeError("dedicated connection required")
    db.execute("BEGIN IMMEDIATE")
    try:
        now = int(time.time())
        row = db.execute("SELECT principal,expires FROM provisioning_sessions WHERE digest=? AND expires>?", (key,now)).fetchone()
        if not row or row[0] not in policy.get("provisioning_admins", ()):
            raise PermissionError("invalid session")
        challenge = secrets.token_bytes(32)
        db.execute("DELETE FROM bound_enrollment WHERE expires<=? OR session_digest=?", (now,key))
        db.execute("INSERT INTO bound_enrollment VALUES (?,?,?,?)", (key,challenge,operator,row[1]))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"challenge":encode(challenge),"rp":{"id":policy["rp_id"],"name":"Recover Trading"},
            "user":{"id":encode(hashlib.sha256(operator.encode()).digest()),"name":operator,"displayName":operator}}
