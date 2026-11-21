# Remaining professional upgrades — inspected baseline and gates

Baseline inspected: `main` at `9ae06299bba588a247a7434eec6195f0c2a7d416`
(merged PR #2). All 431 original offline tests passed before modifications.
This checklist tracks the user's 20 November 2026 remaining-upgrades prompt;
existing code is retained, and source implementation is distinct from
deployment, real broker evidence and operational readiness.

## Current implementation increment

Milestone 1 candidate: [equity checkpoint integrity](EQUITY_CHECKPOINT_RECOVERY.md).
Includes transport receipt validation, immutable additive evidence,
conservative UTC windows, independent read-only collection, durable health
alerts, watchdog heartbeat visibility and rollback/migration tests. Deployment,
authentic next daily/weekly openings and off-machine alert commissioning remain
open. No historical opening was recovered or fabricated by this change.

Milestone 2A candidate: [signed Gold recovery planning](GOLD_RECOVERY_REVIEW.md).
Adds read-only equity-loss prerequisites to the commissioning gate and separate
capture/operator signatures for the prior rejected attempt. It preserves the
consumed lock and has no recovery execution or unlock operation. This is a
review prerequisite, not completion of broker commissioning.

The connector queried during inspection reported both FIRE endpoints disabled
and the Gold attempt rejected with `orders_submitted=false`. Quote data carried
an older timestamp, so these responses were **not accepted as fresh account-wide
broker flatness, current watchdog health, lock verification or deployment proof**.
No VM shell, credentials, services or broker settings were modified.

## Remaining milestones

| Milestone | Existing foundations inspected | Remaining acceptance work |
| --- | --- | --- |
| 1. Checkpoints | `portfolio_equity_guard.py`, `equity_checkpoint_health.py`, watchdog and risk banner | Review/deploy the candidate safely; verify receipt headers, authentic UTC openings, reboot recovery and independent external alert delivery. |
| 2. Commissioning | `fire_entry.py`, `fire_execution.py`, `fire_watchdog.py`, account/portfolio/leverage guards, one-shot Gold command; candidate adds equity preflight and signed recovery-planning review | Review/stage the read-only capture and distinct operator signatures. Separately approve a recovery procedure for the consumed Gold lock; preserve it until then. Commission BTC/Gold lifecycles only after prerequisites and separate explicit operator authorization. No trial ordered by this increment. |
| 3. Accounting | `trade_fill_evidence.py`, `fire_reconciliation.py`, `fire_performance.py`, immutable broker-evidence ledgers | Complete trade inventory and all requested attribution/latency/MFE/MAE/R fields; validate manual/emergency/multi-exit evidence and realized financial reporting against existing broker receipts. Preserve verified-subset exclusions. |
| 4. Decision review | Saved FIRE model inputs, indicators and outcome receipts | Reproducible review schema and mistake taxonomy; predefined no-trade comparison; separate process quality from losing outcomes. |
| 5. Kimi research | `kimi_learning.py`, `trade_memory.py`, event watcher and durable review reservations | Verified accounting-driven review events, held-out lesson tests, contradiction/deduplication/expiry, explicit advisory approvals and rollback; token/currency budgets. Candidates must not influence GPT-6 automatically. |
| 6. Quant validation | Candle archive, quarantine, period levels, technical features | Forward-only backtesting, walk-forward/held-out/shadow comparisons, regime/cost sensitivity, bootstrap/Monte Carlo and selection-leakage controls. No statistical edge has been established. |
| 7. Autonomy | Durable FIRE statuses, reservation, disabled defaults, independent watchdog | Reviewed deterministic transition system and full operational/shadow gates. Keep autonomy disabled; passing tests is not activation authority. |
| 8. DeepSeek | `session.py` XNYS calendar (DST/holidays/early closes), NYSE-session observer, persistent call quota | Verify current VM providers/entitlements and clarify that NYSE scheduling alone does not establish an NYSE equity data feed. Add opportunity scoring/deduplication/outcome evaluation without changing working scanner permissions. |
| 9. Operations/UI | Existing dashboard, checkpoint banner, read-only reconciliation/performance, systemd installers | Broader exposure/protection/incident/billing summaries, release identity, uptime/disk/WAL monitoring and commissioned backup/restore/rollback. Current increment adds checkpoint/collector/watchdog health only. |
| 10. AI costs | `ai_call_budget.py`, pre-AI deterministic gates, Kimi reservations | Per-model token/currency reservations and usage reconciliation, cache attribution and bounded retry policy. Routine monitoring remains deterministic and makes no paid AI calls. |

## Release rules

- Develop on controlled branches; review and relevant tests are required before
  merging into `main`. Do not treat a source merge as a VM deployment.
- Every subsequent increment needs unit/integration/failure/recovery/concurrency
  coverage appropriate to its behavior, broker simulators, independent risk-rule
  checks, security tests, and a rollback procedure. Include migration and mobile
  checks when affected. Never commission by placing unrelated test trades.
- Keep BTC and Gold FIRE disabled, preserve the Gold commissioning lock and
  original evidence, do not change broker leverage automatically, and do not
  restart any trading service during exposure without approved protection.
- GPT-6 alone decides FIRE; DeepSeek scans independently; Kimi proposes research
  with no execution permission or unilateral advisory/policy activation.
