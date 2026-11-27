# Gold V2 cutover preparation — no activation

Candidate branch: recover/gold-v2-rebuild. The live revision, unit names,
arguments, paths and process topology have not been verified on the VM.
The repository's recover-demo.service starts both markets by default.
Never stop or replace a shared BTC/Gold service as a Gold-only cutover.

## Stage A — observation only

Install the reviewed candidate in a separate release directory, not over
the active Recover checkout. The proposed recover-gold-v2-shadow.service
uses /opt/recover-gold-v2/current and /var/lib/recover-trading/gold-v2-shadow.
It has no credentials, no account mutation, and no execution flag.
Do not install the unit until operator authorization. Existing BTC and
Gold execution stay unchanged. Point a separately reviewed dashboard
configuration at the sidecar with --gold-v2-dir if desired; do not restart
the existing dashboard as part of an unapproved rollout.

Record source health, heartbeat freshness, gaps, opportunity count,
validation progress and errors. The offline tests do not verify live
public API response contracts, data quality or execution profitability.

## Stage B — read-only inventory before any cutover

* Identify the exact running legacy Gold and BTC commit, service units,
  command arguments, credentials separation and data directories, locally.
  Redact secrets; never copy environment values into the evidence manifest.
* If Gold and BTC are in a shared process, independent Gold execution
  replacement without BTC interruption is not yet possible. Prepare a
  separately authorized topology migration; preserve all BTC arguments.
* Confirm a consistent SQLite backup (online backup or stopped writer),
  journal paths, permissions, immutable legacy release and rollback revision.
  Do not copy an active SQLite file without accounting for WAL state.
* Wait for naturally flat Gold exposure and no pending exchange orders or
  unresolved submission/management attempts. Do not force close a position
  merely for the migration. Existing positions stay with their current owner.
* Confirm distinct isolated demo account identities, not only different keys.
* Match the exact candidate SHA to completed regression and browser tests.
* Run the offline inventory against the reviewed evidence manifest:
  python3 -m recover_trading.gold_v2_cutover reviewed-manifest.json

The inventory reports operator assertions, not authoritative server facts.
Its activation_ready is deliberately false in this increment.

## Stage C — future authorized execution replacement (not available yet)

Prerequisites: finish execution CLI and exclusive account ownership,
early protective closure attribution, ambiguous submission recovery,
complete position management and exchange integration verification.
Position additions cannot be dispatched until continuous bracket coverage
can be established. Do not start two writers on the Gold account.

Once the prerequisites are verified, prepare a separate version-pinned
Gold-only unit and stop only the verified legacy Gold writer at the agreed
flat handoff. Re-observe account identity, flat state, orders and outstanding
journals after stopping it. Keep old journals read-only, start the new owner
with the approved allocation and verify its status. Do not alter BTC.
No commands for execution activation are included in this revision.

## Rollback

If only the shadow worker is running, stopping it has no effect on trading;
preserve the research data. For a future execution cutover, stop new entry
admission and reconcile orders and ownership first. Do not start the old
strategy while an open V2 episode or uncertain order remains. Revert only
after verified flat state, no residual orders, no unresolved mutations and
exclusive ownership. Restore the exact previous Gold-only unit/commit and
configuration, preserving the newest journals and fills (never overwrite
post-cutover evidence with an old backup). BTC must remain unchanged.
