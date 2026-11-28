"""Offline runner contract. Inject only a trusted fixture command simulator.
No subprocess implementation or live service access."""
from restart_plan import restart_plan, status_plan
from execution_journal import finish

def run_fixture(db, request_id, clock, simulate):
    row=db.execute("SELECT target,status FROM executions WHERE request_id=?",(request_id,)).fetchone()
    if row != ("fixture","reserved"):
        raise ValueError("fixture reservation required")
    outcome="unknown"
    try:
        result=simulate(restart_plan("fixture"),timeout=30,output_limit=4096)
        if result.get("returncode")==0:
            status=simulate(status_plan("fixture"),timeout=10,output_limit=4096)
            if status.get("returncode")==0 and status.get("stdout")=="ActiveState=active\nSubState=running\nResult=success\n":
                outcome="succeeded"
    finally:
        finish(db,request_id,outcome,clock())
    return {"status":outcome,"execution_effect":"none"}
