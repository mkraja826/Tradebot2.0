"""Fixture-only transaction boundary; caller owns private database connection."""
import sqlite3
from approval_verify import verify
from executor_policy import validate_request

def reserve_fixture(db, request, envelope, key, clock, operators, state):
    if db.in_transaction:
        raise ValueError("exclusive transaction required")
    db.execute("BEGIN IMMEDIATE")
    try:
        now=clock()
        target,revision=validate_request(request,now,{"fixture"})
        claims=verify(request,envelope,key,now,"fixture",operators)
        if state.get("revision")!=revision or state.get("safe_to_restart") is not True:
            raise ValueError("state precondition failed")
        db.execute("INSERT INTO consumed VALUES (?,?,?)",(claims["nonce"],claims["digest"],now))
        db.execute("INSERT INTO executions(request_id,digest,target,status,started) VALUES (?,?,?,'reserved',?)",(request["id"],claims["digest"],target,now))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"status":"reserved","execution_effect":"none"}
