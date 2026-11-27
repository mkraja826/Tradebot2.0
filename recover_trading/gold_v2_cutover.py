"""Offline cutover readiness inventory. Never starts, stops or changes a service.

Input is an operator-reviewed evidence manifest, not a trusted server attestation.
The output cannot authorize live/demo execution.
"""
import argparse
import json
import re
from pathlib import Path

VERSION="gold-v2-cutover.2"

def assess(m):
    if not isinstance(m,dict):raise ValueError("manifest_object_required")
    checks={}
    def add(k,ok):checks[k]="reported_ready" if ok else "unverified"
    def sha(k):return isinstance(m.get(k),str) and re.fullmatch(r"[0-9a-f]{40}",m[k]) is not None
    add("running_revision",sha("legacy_running_sha"))
    add("candidate_revision",sha("candidate_sha") and m.get("ci_passed_sha")==m.get("candidate_sha"))
    add("isolated_gold_process",m.get("legacy_gold_process_scope")=="gold_only")
    add("distinct_demo_accounts",m.get("distinct_demo_accounts_verified") is True)
    add("gold_flat_and_orders_empty",m.get("gold_flat_verified") is True and m.get("gold_active_orders_empty_verified") is True)
    add("journal_backup",m.get("consistent_backup_verified") is True)
    add("rollback_revision",sha("rollback_sha") and m.get("rollback_sha")==m.get("legacy_running_sha"))
    add("shadow_health",m.get("shadow_health_verified") is True)
    add("live_feed_compatibility",m.get("live_feed_compatibility_verified") is True)
    add("exclusive_gold_owner",m.get("exclusive_gold_owner_verified") is True)
    add("btc_unchanged",m.get("btc_config_preserved_verified") is True)
    # These are known engineering gaps in the candidate, not operator flags.
    blockers=["execution_runtime_integration_unverified","early_bracket_closure_attribution_incomplete",
              "position_addition_atomic_coverage_unverified","exchange_integration_not_verified"]
    return {"version":VERSION,"mode":"offline_inventory","execution_effect":"none",
            "operator_reported_checks":checks,"unverified_checks":[k for k,v in checks.items() if v=="unverified"],
            "engineering_blockers":blockers,"activation_ready":False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest")
    args=p.parse_args()
    data=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    print(json.dumps(assess(data),indent=2,allow_nan=False))

if __name__=="__main__":main()
