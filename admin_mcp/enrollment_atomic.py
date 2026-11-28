"""Trusted provisioning completion; requires a dedicated SQLite connection."""
import time
from provisioning_session import digest
from enrollment_controller import check_scope
from passkey_enroll import verify_enrollment

def complete(db, policy, token, operator, challenge, response_json):
    check_scope(operator, policy)
    key = digest(token)
    if not isinstance(challenge, bytes) or len(challenge) != 32:
        raise ValueError("invalid challenge")
    if not isinstance(response_json, str) or not 0 < len(response_json) <= 65536:
        raise ValueError("invalid response")
    if db.in_transaction:
        raise RuntimeError("dedicated transaction required")
    db.execute("BEGIN IMMEDIATE")
    try:
        now = int(time.time())
        row = db.execute("SELECT principal FROM provisioning_sessions WHERE digest=? AND expires>? AND operator=?", (key, now, operator)).fetchone()
        if not row or row[0] not in policy.get("provisioning_admins", ()):
            raise PermissionError("invalid session")
        row = db.execute("SELECT 1 FROM bound_enrollment WHERE session_digest=? AND challenge=? AND operator=? AND expires>?", (key, challenge, operator, now)).fetchone()
        if not row:
            raise ValueError("invalid challenge")
        record = verify_enrollment(response_json, challenge, operator, policy)
        now = int(time.time())
        if db.execute("DELETE FROM provisioning_sessions WHERE digest=? AND expires>?", (key, now)).rowcount != 1:
            raise PermissionError("expired session")
        if db.execute("DELETE FROM bound_enrollment WHERE session_digest=? AND challenge=? AND operator=? AND expires>?", (key, challenge, operator, now)).rowcount != 1:
            raise ValueError("expired challenge")
        db.execute("INSERT INTO credentials(id,operator,public_key,sign_count) VALUES (?,?,?,?)", (record["id"],operator,record["public_key"],record["sign_count"]))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return record["id"]
