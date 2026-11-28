"""In-process integration fixture. No network listener or production access."""
import sqlite3
import secrets
from passkey_store import CredentialStore
from enrollment_store import initialize_enrollment
from gateway_api import FixtureAPI
from gateway_http import application

def build_fixture():
    db=sqlite3.connect(":memory:")
    try:
        store=CredentialStore(db)
        initialize_enrollment(db)
        request_id=secrets.token_hex(16)
        origin="https://fixture.example"
        policy={"operators":["fixture-owner"],"audience":"fixture","rp_id":"fixture.example","origin":origin}
        api=FixtureAPI({request_id:{"id":request_id,"action":"test_only","target":"fixture"}},store,policy,secrets.token_bytes(32))
        app=application(api,origin,policy["rp_id"],[])
        return db,request_id,app
    except Exception:
        db.close()
        raise
