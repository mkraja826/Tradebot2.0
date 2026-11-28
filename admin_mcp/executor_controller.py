"""Development controller. Fixture execution only; no production operations."""
from approval_verify import verify
from approval_ledger import consume
from executor_policy import validate_request

def authorize_fixture(request, envelope, key, db, clock, operators, state):
    now=clock()
    target,revision=validate_request(request,now,{"fixture"})
    claims=verify(request,envelope,key,now,"fixture",operators)
    # State is supplied by a trusted fixture, never by the request.
    if state.get("revision")!=revision or state.get("safe_to_restart") is not True:
        raise ValueError("state precondition failed")
    now=clock()
    validate_request(request,now,{"fixture"})
    consume(db,claims,now)
    return {"status":"authorized_fixture","target":target,"execution_effect":"none"}
