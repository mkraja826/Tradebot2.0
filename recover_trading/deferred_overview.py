"""Unified read-only view of deferred research, never a trade input."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from .reference_positioning import report as positioning
from .gold_release_research import report as economics
from .gold_reopen_research import report as reopening
VERSION="deferred-research-overview-v1"

def report(root,symbol,now):
    # Explicit data root, sibling research stores; never create or modify journals.
    parent=Path(root).parent
    out={"version":VERSION,"symbol":symbol,"execution_effect":"none","rules":[]}
    if symbol=="BTCUSD":
        p=parent/"liquidation-research"
        r=positioning(p/"positioning.sqlite",p/"events.sqlite",now*1000)
        out["positioning"]=r
        latest=None
        try:
            with closing(sqlite3.connect((p/"hypotheses.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
                row=db.execute("SELECT observed_ms,payload FROM observations WHERE observed_ms<=? ORDER BY bucket DESC LIMIT 1",(now*1000,)).fetchone()
                if row:
                    latest=json.loads(row[1]);out["prototype_observed_ms"]=row[0]
                    out["prototype_fresh"]=0<=now*1000-row[0]<=180000
        except (sqlite3.Error,ValueError,TypeError):pass
        rows={x["id"]:x for x in (latest or {}).get("rules",[])}
        for ident in ("B17","B18"):
            v=rows.get(ident,{})
            out["rules"].append({"id":ident,"stage":"experimental_prototype","status":v.get("status","journal_unavailable") if out.get("prototype_fresh") else "stale_or_unavailable","direction":v.get("direction"),"execution_enabled":False})
    elif symbol=="XAUTUSD":
        p=parent/"economic-research"
        e=economics(p,now);g=reopening(p,now)
        out.update(economic=e,reopening=g)
        rules={r["id"]:r for r in e.get("rules",[])}
        for ident in ("G20","G21"):
            source=(e.get("feed_probe") or {}).get("sources",{}).get(ident,{})
            out["rules"].append({"id":ident,"stage":"data_dependent_framework","status":rules.get(ident,{}).get("status","journal_unavailable"),"source_status":source.get("status"),"http_status":source.get("http_status"),"consensus_status":source.get("consensus_status"),"execution_enabled":False})
        out["rules"].append({"id":"G25","stage":"data_dependent_framework","status":g["comparison"]["status"],"source_status":g["licensed_trade_feed"],"execution_enabled":False})
    return out
