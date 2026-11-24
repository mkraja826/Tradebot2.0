"""Append-only settlement evidence research; never affects entry eligibility."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from tradebot.m20_subaccount_baseline_v3 import read_private
from tradebot.opportunity_journal_v3 import digest,canonical
from tradebot.research_collector_v3 import atomic_json

def project(r,now):
    if r["mode"]!="settlement_learning_research_only" or r["execution_authorized"] is not False or r["orders_submitted"]!=0 or r["paid_ai_requests"]!=0 or r["parent_equity_included"] is not False:
        raise ValueError("wrong_source")
    if type(r["checked_at"]) is not int or not 0<=now-r["checked_at"]<=600:raise ValueError("stale_source")
    if set(r["markets"])!={"BTCUSD","XAUTUSD"}:raise ValueError("wrong_scope")
    out=dict(mode="settlement_evidence_archive_research_only",source_checked_at=r["checked_at"],source_sha256=digest(r),markets={},execution_authorized=False,strategy_eligibility_changed=False)
    for s,a in r["markets"].items():
        if a["status"]!="complete_broker_window":raise ValueError("incomplete_coverage")
        n,v,u=(a[k] for k in ("fire_receipts","verified_closed","unverified_or_open"))
        reasons=a["unverified_reasons"];timing=a["wallet_attribution_diagnostics"]
        if any(type(x) is not int or x<0 for x in [n,v,u,*reasons.values(),*timing.values()]) or n!=v+u or sum(reasons.values())!=u:raise ValueError("count_mismatch")
        no_order=reasons.get("broker_order_not_submitted",0)
        ambiguous=reasons.get("unattributed_wallet_posting",0)
        missing_ref=timing.get("receipts_with_after_flat_without_order_or_fill_ref",0)
        if missing_ref>ambiguous:raise ValueError("timing_scope_mismatch")
        out["markets"][s]=dict(receipts=n,verified_closed=v,no_order=no_order,unresolved=u-no_order,
            ambiguous_wallet_attribution=ambiguous,receipts_with_delayed_unlinked_postings=missing_ref,
            verified_learning_available=v>0,model_quality=None,attribution_policy="explicit_signed_ownership_required")
    return out

def archive(root,*,now):
    root=Path(root);r=json.loads(read_private(root/"m21-settlement-learning-v3.json"));out=project(r,now)
    p=root/"m21-settlement-archive-v3.sqlite"
    if p.is_symlink():raise ValueError("untrusted_archive")
    with closing(sqlite3.connect(p,timeout=5)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS snapshots(source_hash TEXT PRIMARY KEY,source_checked_at INTEGER NOT NULL,payload TEXT NOT NULL)")
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op} BEFORE {op} ON snapshots BEGIN SELECT RAISE(ABORT,'immutable research evidence');END")
        db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?)",(out["source_sha256"],out["source_checked_at"],canonical(out)))
        if db.execute("SELECT payload FROM snapshots WHERE source_hash=?",(out["source_sha256"],)).fetchone()[0]!=canonical(out):raise ValueError("archive_conflict")
        count=db.execute("SELECT count(*) FROM snapshots").fetchone()[0]
    atomic_json(root/"m21-settlement-archive-v3.json",out)
    return out,count
