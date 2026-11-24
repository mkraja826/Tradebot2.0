"""Independent read-only monitor. A failure never writes scanner state."""
from pathlib import Path
from time import time
from tradebot.market_data_v3 import MARKETS
from tradebot.dashboard_context_v3 import read_accounts
from tradebot.position_observer_v3 import view
from tradebot.position_journal_v3 import PositionJournal
from tradebot.research_collector_v3 import atomic_json

def tick(root,*,reader=read_accounts,clock=time):
    root=Path(root)
    try: accounts=reader()
    except Exception: accounts={}
    now=clock()
    journal=PositionJournal(root/"positions-v3.sqlite")
    status={"mode":"read_only_position_monitor","checked_at":int(now),"markets":{},
            "orders_submitted":0,"ai_requests":0,"scanner_control":False,"execution_authorized":False}
    for s in MARKETS:
        try:
            v=view(s,accounts.get(s,{}),now=now)
            change=journal.record(v)
            last=journal.last(s)
            status["markets"][s]={"current":v,"journal_result":change,
                "last_verified_observation":last["observed_at"] if last else None}
        except Exception as e:
            status["markets"][s]={"current":{"symbol":s,"status":"unknown","reason":type(e).__name__}}
    status["journal_changes"]=journal.counts()
    atomic_json(root/"position-monitor-status.json",status)
    return status

if __name__=="__main__":
    import argparse,json
    p=argparse.ArgumentParser(); p.add_argument("--directory",type=Path,required=True)
    r=tick(p.parse_args().directory)
    print(json.dumps({"checked_at":r["checked_at"],"markets":{s:x["current"]["status"] for s,x in r["markets"].items()},"journal_changes":r["journal_changes"]}))
