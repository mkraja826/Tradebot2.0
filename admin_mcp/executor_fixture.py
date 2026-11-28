"""Test-only executor; deliberately has no system or trading operations."""
from approval_verify import verify
from approval_ledger import consume

def execute_fixture(db, request, envelope, key, now, operators):
    if not isinstance(request, dict) or set(request) != {"id", "action", "target"}:
        raise ValueError("invalid fixture request")
    if request["action"] != "test_only" or request["target"] != "fixture":
        raise ValueError("operation not allowed")
    claims = verify(request, envelope, key, now, "fixture", operators)
    consume(db, claims, now)
    return {"id": request["id"], "status": "succeeded", "execution_effect": "none"}
