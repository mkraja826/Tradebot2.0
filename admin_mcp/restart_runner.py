"""Fixture only. Unknown status retains the target lock during execution."""
from restart_plan import restart_plan, status_plan

def run_fixture(db, request_id, clock, simulate):
    if db.in_transaction:
        raise ValueError("exclusive transaction required")
    with db:
        changed=db.execute("UPDATE executions SET status='unknown' WHERE request_id=? AND target='fixture' AND status='reserved'",(request_id,)).rowcount
        if changed!=1:
            raise ValueError("unclaimed fixture reservation required")
    outcome="unknown"
    try:
        result=simulate(restart_plan("fixture"),timeout=30,output_limit=4096)
        if result.get("returncode")==0:
            status=simulate(status_plan("fixture"),timeout=10,output_limit=4096)
            if status.get("returncode")==0 and status.get("stdout")=="ActiveState=active\nSubState=running\nResult=success\n":
                outcome="succeeded"
    finally:
        with db:
            if db.execute("UPDATE executions SET status=?,finished=? WHERE request_id=? AND status='unknown' AND finished IS NULL AND started<=?",(outcome,clock(),request_id,clock())).rowcount!=1:
                raise ValueError("outcome unavailable")
    return {"status":outcome,"execution_effect":"none"}
