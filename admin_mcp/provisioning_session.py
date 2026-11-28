"""Local administrator-issued provisioning tokens.
Issuance must remain restricted to the trusted VM administrator.
Never expose issue() through HTTP or MCP.
"""
import hashlib
import secrets
import time

def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS provisioning_sessions (digest BLOB PRIMARY KEY, principal TEXT NOT NULL, expires INTEGER NOT NULL)")
    db.commit()

def digest(token):
    if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("invalid provisioning token")
    return hashlib.sha256(token.encode("ascii")).digest()

def issue(db, principal, policy):
    if not isinstance(principal, str) or not principal or principal not in policy.get("provisioning_admins", ()):
        raise PermissionError("unauthorized provisioning administrator")
    token = secrets.token_hex(32)
    with db:
        db.execute("DELETE FROM provisioning_sessions WHERE expires<=?", (int(time.time()),))
        db.execute("INSERT INTO provisioning_sessions VALUES (?,?,?)", (digest(token), principal, int(time.time())+300))
    return token

def authenticate(db, token):
    try:
        key = digest(token)
    except ValueError:
        return None
    row = db.execute("SELECT principal FROM provisioning_sessions WHERE digest=? AND expires>?", (key,int(time.time()))).fetchone()
    return row[0] if row else None

def consume(db, token):
    with db:
        count = db.execute("DELETE FROM provisioning_sessions WHERE digest=? AND expires>?", (digest(token),int(time.time()))).rowcount
        if count != 1:
            raise PermissionError("provisioning session unavailable")
