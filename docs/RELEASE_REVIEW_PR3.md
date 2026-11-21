# PR #3 release review — 21 November 2026

Scope: source safety review of `be6e55c954f05240211fe53d549354bce0b14749`
against `main` at `9ae06299bba588a247a7434eec6195f0c2a7d416`.
This review was performed by the implementing assistant in a later review pass;
it is not an independent human review or approval to deploy or trade.

## Blocking finding and correction

**P0: automatic replacement of missing equity history.** Runtime guard
construction created SQLite files and initialized their schema. If the risk
ledger disappeared, the collector could adopt a later wallet balance as a new
peak and eventually approve risk after new openings, forgetting earlier loss
history. Dashboard/controller initialization could also recreate that file.

The defect was reproduced without broker access: an isolated original ledger
with a peak of 2000 was moved to a preserved fixture path; the old collector
created a replacement ledger with peak 1000 from a mocked current wallet read.
No real account data, credentials, services or locks were involved.

The correction introduces lazy, existing-only runtime access:

- Require original observations and a consistent watermark before additive
  migration or wallet collection. Missing/empty/corrupt history is a blocker.
- Use SQLite `mode=rw` for runtime connections, without automatic creation.
  Bind file device/inode and check before/after opening and after persistence.
- Retain immutable rows, original checkpoints and unchanged 2%/5%/8% limits.
- Defer risk access during controller startup so read-only diagnostics can
  report a missing/corrupt ledger instead of crashing the dashboard.
- Keep the explicit initialization helper for isolated fixtures and separately
  reviewed first-time provisioning only. No runtime reset/bootstrap API exists.

## Validation

The reviewed PR #3 candidate passes 483 offline tests. Thirteen added tests
cover missing paths/files, zero-byte replacement, empty schemas, absent
watermarks, legacy migration, unchanged peak/loss enforcement, live file
replacement, symlink substitution, deletion between checks and SQLite open,
concurrent opens, collector recovery refusal and diagnostic controller startup.

The full suite also retains existing UTC/IST/rollover, immutable evidence,
broker-response, corruption, watchdog failure, restart, concurrency, backup,
security and performance tests. The unchanged dashboard assets retain their
previous passing mobile browser checks. These are fixture/code checks only.

## Release boundaries

The source changes do not start services, change leverage, enable FIRE,
clear the Gold lock or fabricate checkpoints. No actual broker commissioning
was attempted. Remaining operational acceptance still includes authentic
openings, verified HTTP timing behavior, supervised deployment/reboot recovery,
external alert delivery and independently reviewed broker protection evidence.

Do not roll back by deleting or replacing evidence. Earlier runtime code can
create missing ledgers: if original history is unavailable, keep FIRE disabled
and equity ingestion stopped until approved recovery preserves the original
history. See [the deployment and rollback procedure](EQUITY_CHECKPOINT_RECOVERY.md).

## Independent agent review follow-up

A separate reviewer agent reproduced a second blocking defect in the published
`73c4d552faa71ae75e17f2c7b1121bad4fe7033c` candidate: lowering the mutable
watermark from 1100 to 1000 left older immutable equity of 1100 intact, yet
runtime and health checks accepted a later 1000 observation. The resulting
9.09% historical drawdown should exceed the unchanged 8% limit.

The correction validates the watermark against **all** immutable observations
using exact Decimal comparisons, both on existing-only startup and inside
every observation transaction. Read-only checkpoint health uses the same
check. Lowered peaks are rejected without repairing or rewriting evidence;
higher stored watermarks are preserved conservatively. New fixture tests
cover restart, cached guards, precision and text ordering, genuine new-period
openings, attempted wallet-based repair and rejection before legacy migration.

The existing production-shaped monthly-history performance check is retained.
Rollback to code without this check is not a recovery method for inconsistent
watermarks: keep FIRE disabled and preserve the original ledger for separately
approved reconciliation. This record documents the finding and implementation;
the final independent review result is recorded on the pull request.
