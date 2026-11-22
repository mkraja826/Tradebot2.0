# BTC DEMO release evidence — independent watchdog and wallet-risk checks

## Confirmed gap
The read-only `demo_release_evidence` audit previously checked authenticated
opening-equity receipts with `checkpoint_health` but did **not** demand
recent independent watchdog/equity-monitor heartbeats. It could report
`limited_read_only_checks_consistent_not_execution_authority` when systemd
services were running but their actual watchdog protection loop was stale.

It also skipped the existing **fresh signed-wallet equity loss-budget**
assessment. A valid opening checkpoint establishes a starting balance; it
does NOT show that today's, this week's and the since-observation peak drawdown
are still within policy.

## Change
The release audit now:
1. Uses `risk_health` for both initial and final equity checks. Require
   `healthy` opening/equity receipts **and** independent watchdog heartbeat
   age <=90 seconds, collector age <=180 seconds, both statuses `healthy`,
   and zero monitoring alerts. Missing monitoring data fails closed.
2. Before a broker position inventory, calls the already implemented
   `signed_equity_readiness` once using **authenticated DEMO wallet GETs**.
   The result must have valid receipt/provenance, genuine daily/weekly anchors,
   read-only mode, immutable ledger unchanged, `trade_authorized=false`,
   `is_reconciled_realized_pnl=false`, explicit
   `within_observed_equity_limits` policy outcome and healthy monitoring.
3. Refuses even a *limited diagnostic consistency* label when the current
   equity-budget read fails, the daily limit is exceeded, the weekly limit is
   exceeded, the historic peak drawdown exceeds policy, or watchdog/collector
   telemetry disappears before the final recheck.
4. Reports only check booleans and fixed blocker codes; **never exposes**
   signed transport receipts, private account balances, API keys, user order
   identifiers or full wallet responses in the consolidated report.
5. Keeps `broker_wide_fill_and_funding_reconciliation_complete=false`,
   `historical_continuous_protection_proven=false`,
   `trade_authorized=false`, `safe_to_enable_fire=false`, and
   `ready_for_unattended_trading=false` regardless of any successful check.

The operator's `ops/run_btc_demo_release_audit.sh` equity phase also uses
`risk_health` (not merely checkpoint-only health), with the same recent
watchdog/collector heartbeat requirement. The launcher still exits **2**
without setting trading authority.

## Important boundaries
- A systemd `active` service is not proof the watchdog loop is processing
  protection. Heartbeats are checked from the independent monitoring ledger.
- Today's and Monday's signed opening observations must exist from the actual
  `[00:00:00,00:05:00) UTC` window. No backfill, reset, inferred baseline or
  retroactive receipt insertion is provided. The separate open PR #30 fixes
  the exclusive upper bound consistently; review and deploy it before relying
  on a boundary case.
- The 2% daily / 5% weekly / 8% historic observed-peak proxy remain
  conservative equity declines, **not reconciled realized trade losses**;
  cash transfers/funding remain separately under M09 broker reconciliation.
- A healthy wallet risk result says nothing about account-wide flatness or
  next-trade liquidation risk by itself.
- Source CI cannot prove the VM has been updated, that genuine broker
  observations exist, alerts reach an off-host phone, or stop-loss/take-profit
  protection remained continuously live.
- Only Delta India DEMO is supported. No execution in this diagnostic, no paid
  LLM use, no service restart, no ledger or order mutation, and no release or
  sign-off is automatic.
