"""Synthetic crash-recovery inspection. Never retries or submits an order."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from tradebot.opportunity_journal_v3 import digest
from tradebot.synthetic_lifecycle_v3 import project

def inspect(path,preview):
    base=dict(mode="synthetic_restart_review",status="evidence_unavailable",
              execution_authorized=False,retry_authorized=False,
              orders_submitted=0,broker_verified=False,settlement_verified=False)
    try:
        if preview["mode"]!="synthetic_execution_preview" or preview["execution_authorized"] is not False or preview["orders_submitted"]!=0:
            return base
        p=Path(path)
        if p.is_symlink() or not p.is_file():return base
        with closing(sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):return base
            eid=preview["event_id"]
            row=db.execute("SELECT preview_hash,payload FROM entries WHERE event_id=?",(eid,)).fetchone()
            if row is None:return base
            if row[0]!=digest(preview) or digest(json.loads(row[1]))!=row[0]:return dict(base,status="conflicting_preview")
            rows=db.execute("SELECT stamp,payload FROM observations WHERE event_id=? ORDER BY stamp LIMIT 10001",(eid,)).fetchall()
            if len(rows)>10000:return base
            known=0;terminal=None;latest=None
            for stamp,raw in rows:
                item=json.loads(raw)
                if type(stamp) is not int or stamp<=0 or item["stamp"]!=stamp:return base
                r=project(preview,item["receipt"],item["protections"])
                if r!=item["observation"]:return dict(base,status="conflicting_observation")
                q=r["filled_contracts"];state=r["entry_state"]
                if q is not None:
                    if q<known or (terminal is not None and terminal!=(state,q)):return dict(base,status="conflicting_observation")
                    known=q
                    if state in ("fixture_filled","fixture_rejected"):terminal=(state,q)
                latest=r
        out=dict(base,prior_known_filled_contracts=known)
        if latest is None or latest["filled_contracts"] is None:return dict(out,status="unresolved_requires_reconciliation")
        if latest["filled_contracts"]>0:
            state="fixture_protection_reported" if latest["protection_state"]=="fixture_bracket_matched" else "fixture_protection_missing"
        elif latest["entry_state"]=="fixture_rejected" and latest["protection_state"]=="not_required":state="fixture_rejected_observed"
        else:state="fixture_pending_or_unexpected_inventory"
        return dict(out,status=state)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,ArithmeticError):return base
